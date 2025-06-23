import socket
import os
import base64
import threading
import shutil  # Added for recursive directory deletion
import sys  # Added for command line argument handling
import logging
import hashlib  # Added for MD5 calculation
import json    # Added for manifest handling
from dataclasses import dataclass
from typing import Optional, Set, Dict
import time
from pathlib import Path

def calculate_md5(file_path: Path) -> Optional[str]:
    """A standalone helper function to calculate MD5 hash of a single file"""
    hash_md5 = hashlib.md5()
    try:
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        result = hash_md5.hexdigest()
        print(f"Debug: Calculated MD5 for {file_path}: {result}")
        return result
    except IOError as e:
        print(f"Error calculating MD5 for {file_path}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error calculating MD5 for {file_path}: {e}")
        return None

def generate_md5_manifest(directory: Path) -> Dict[str, str]:
    """Generate MD5 manifest for all files in directory"""
    manifest = {}
    try:
        # 使用 rglob 递归扫描所有文件
        for item in directory.rglob('*'):
            try:
                # 获取相对于基础目录的路径
                rel_path = item.relative_to(directory)
                # 转换为字符串并统一使用正斜杠
                rel_path_str = str(rel_path).replace('\\', '/')
                
                if item.is_dir():
                    manifest[rel_path_str] = "__DIR__"
                    print(f"Debug: Added directory to manifest: {rel_path_str}")
                elif item.is_file():
                    md5 = calculate_md5(item)
                    manifest[rel_path_str] = md5
                    print(f"Debug: Added file to manifest: {rel_path_str} (MD5: {md5})")
            except Exception as e:
                print(f"Debug: Error processing {item}: {e}")
                continue
    except Exception as e:
        print(f"Debug: Error scanning directory {directory}: {e}")
    
    print(f"Debug: Generated manifest with {len(manifest)} items")
    return manifest

@dataclass
class ServerConfig:
    """Server configuration class"""
    base_dir: Path = Path("serverfile").resolve()
    default_port: int = 51234
    base_data_port: int = 51235
    host: str = ''
    buffer_size: int = 8192
    data_buffer_size: int = 2048
    upload_buffer_size: int = 4096

    @classmethod
    def from_args(cls) -> 'ServerConfig':
        """Create config from command line arguments, using the class's default port."""
        if len(sys.argv) == 1:
            # 直接使用类中定义的默认端口
            print(f"[INFO] No port provided. Using default port: {cls.default_port}")
            return cls()  # 无需传入参数，它会使用数据类中定义的默认值
        elif len(sys.argv) == 2:
            try:
                port = int(sys.argv[1])
                print(f"[INFO] Port specified by user: {port}")
                # 创建实例时覆盖默认端口
                return cls(default_port=port)
            except ValueError:
                # 将错误信息输出到标准错误流，这是更好的实践
                print(f"[ERROR] Invalid port '{sys.argv[1]}'. Port must be a number.", file=sys.stderr)
                sys.exit(1)
        else:
            print("[ERROR] Too many arguments. Usage: python3 server.py [port]", file=sys.stderr)
            sys.exit(1)

class FileTransferHandler:
    """Handles file transfer operations"""
    def __init__(self, config: ServerConfig):
        self.config = config
        self.chunk_size = 1024 # 定义块大小，应与客户端匹配

    def handle_file_transfer(self, filename: str, data_port: int, client_path: Path) -> None:
        """Handle complete file transfer process on a new port to match the new client logic."""
        data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        data_sock.bind((self.config.host, data_port))
        print(f"[+] Data socket is now listening on port {data_port} for '{filename}'...")

        file_path = client_path / filename
        if not file_path.is_file():
            print(f"!!! [Data Port] File not found at path: {file_path}")
            data_sock.close()
            return
            
        try:
            # 1. 等待客户端的初始握手信号
            request_bytes, client_addr = data_sock.recvfrom(self.config.data_buffer_size)
            request = request_bytes.decode('utf-8')
            print(f"    [Data Port] Received from {client_addr}: '{request}'")

            if request == f"DOWNLOAD {filename}":
                # 2. 回复DOWNLOAD_READY，告诉客户端可以开始请求数据了
                data_sock.sendto(b"DOWNLOAD_READY", client_addr)
                print(f"    [Data Port] Sent DOWNLOAD_READY to {client_addr}. Starting transfer...")

                # 3. 打开文件，准备分块发送
                with file_path.open('rb') as f:
                    while True:
                        # 4. 等待客户端的 "GET_CHUNK" 请求
                        chunk_req_bytes, recv_addr = data_sock.recvfrom(self.config.data_buffer_size)
                        if chunk_req_bytes.decode('utf-8') != "GET_CHUNK":
                            # 如果收到意外的请求，则停止传输
                            break
                        
                        chunk_data = f.read(self.chunk_size)
                        if not chunk_data:
                            # 5. 文件读取完毕，发送传输完成信号
                            data_sock.sendto(b"TRANSFER_COMPLETE", client_addr)
                            print(f"[+] File transfer for '{filename}' completed.")
                            break
                        
                        # 6. 发送数据块
                        encoded_chunk = base64.b64encode(chunk_data).decode('utf-8')
                        response = f"DATA {encoded_chunk}"
                        data_sock.sendto(response.encode('utf-8'), client_addr)
            else:
                print(f"!!! [Data Port] Expected 'DOWNLOAD {filename}' but received '{request}'. Aborting.")

        except socket.timeout:
            print(f"!!! [Data Port] Socket timed out during transfer for '{filename}'.")
        except Exception as e:
            print(f"!!! [Data Port] An error occurred during file transfer: {e}")
        finally:
            data_sock.close()
            print(f"[-] Data socket on port {data_port} has been closed.")

    def receive_file_data(self, sock: socket.socket, original_client_addr: tuple, target_file_path: Path) -> None:
        """Receive complete file data on the main socket"""
        print(f"    [Util] Receiving data for -> {target_file_path.absolute()}")
        try:
            target_file_path.parent.mkdir(parents=True, exist_ok=True)
            with target_file_path.open('wb') as f:
                while True:
                    data_bytes, recv_addr = sock.recvfrom(self.config.upload_buffer_size)
                    data_message = data_bytes.decode('utf-8')
                    if data_message == "UPLOAD_DONE":
                        sock.sendto(b"UPLOAD_COMPLETE", original_client_addr)
                        print(f"    [Util] File receive complete.")
                        break
                    if data_message.startswith("DATA "):
                        chunk_data = base64.b64decode(data_message.split(' ', 1)[1])
                        f.write(chunk_data)
                        sock.sendto(b"ACK_DATA", original_client_addr)
        except Exception as e:
            print(f"!!! [Util] Error during file data reception: {e}")

class FolderHandler:
    """Handles folder operations and folder upload functionality"""
    def __init__(self, config: ServerConfig):
        self.config = config
        self.sessions = {}  # Store upload sessions
        self.max_folder_depth = 10  # Maximum allowed folder depth
        self.max_path_length = 255  # Maximum path length

    def create_folder_structure(self, root_folder_name: str, current_client_path: Path, 
                              folder_structure: str, client_addr: tuple) -> bool:
        """
        Create folder structure for upload
        Returns True if successful, False otherwise
        """
        try:
            base_path = current_client_path / root_folder_name
            real_base_path = base_path.resolve()
            
            # Security check: ensure the path is within server directory
            if not str(real_base_path).startswith(str(self.config.base_dir)):
                print(f"[ERROR] Attempted to create folder outside server directory: {real_base_path}")
                return False

            # Create base directory
            base_path.mkdir(parents=True, exist_ok=True)
            
            # Store session information
            self.sessions[client_addr] = {
                'base_path': base_path,
                'created_dirs': set(),
                'start_time': time.time()
            }

            # Process folder structure
            for rel_dir in folder_structure.split('\n'):
                if not rel_dir:
                    continue
                    
                # Convert to Path object and normalize
                rel_path = Path(rel_dir.replace('/', os.path.sep))
                
                # Security checks
                if '..' in str(rel_path) or rel_path.is_absolute():
                    print(f"[ERROR] Invalid path in folder structure: {rel_path}")
                    return False
                    
                # Check path length
                if len(str(rel_path)) > self.max_path_length:
                    print(f"[ERROR] Path too long: {rel_path}")
                    return False
                    
                # Check folder depth
                if len(rel_path.parts) > self.max_folder_depth:
                    print(f"[ERROR] Folder depth exceeds maximum: {rel_path}")
                    return False

                full_path = base_path / rel_path
                full_path.mkdir(parents=True, exist_ok=True)
                self.sessions[client_addr]['created_dirs'].add(full_path)

            return True

        except Exception as e:
            print(f"[ERROR] Failed to create folder structure: {e}")
            return False

    def get_upload_path(self, client_addr: tuple, relative_file_path: str) -> Optional[Path]:
        """
        Get the full path for file upload within a folder upload session
        Returns None if session is invalid or path is invalid
        """
        session = self.sessions.get(client_addr)
        if not session:
            return None

        try:
            # Convert to Path object and normalize
            rel_path = Path(relative_file_path.replace('/', os.path.sep))
            
            # Security checks
            if '..' in str(rel_path) or rel_path.is_absolute():
                print(f"[ERROR] Invalid file path: {rel_path}")
                return None
                
            # Check path length
            if len(str(rel_path)) > self.max_path_length:
                print(f"[ERROR] File path too long: {rel_path}")
                return None

            full_path = session['base_path'] / rel_path
            real_path = full_path.resolve()
            
            # Security check: ensure the file is within the upload directory
            if not str(real_path).startswith(str(session['base_path'].resolve())):
                print(f"[ERROR] Attempted to upload file outside upload directory: {real_path}")
                return None

            # Ensure parent directory exists
            full_path.parent.mkdir(parents=True, exist_ok=True)
            return full_path

        except Exception as e:
            print(f"[ERROR] Failed to get upload path: {e}")
            return None

    def cleanup_session(self, client_addr: tuple) -> None:
        """Clean up upload session"""
        if client_addr in self.sessions:
            session = self.sessions[client_addr]
            # Optionally, you could add cleanup logic here
            # For example, removing empty directories
            self.sessions.pop(client_addr)

    def is_session_valid(self, client_addr: tuple) -> bool:
        """Check if the upload session is valid"""
        if client_addr not in self.sessions:
            return False
            
        session = self.sessions[client_addr]
        # Check if session has expired (e.g., 30 minutes)
        if time.time() - session['start_time'] > 1800:
            self.cleanup_session(client_addr)
            return False
            
        return True

class SyncHandler:
    """Handles file synchronization on the server side."""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.sessions = {}  # Store sync sessions
        
    def start_sync_session(self, client_addr: tuple, remote_path: str, total_chunks: int) -> bool:
        """Start a new sync session for a client."""
        try:
            session_key = f"sync-{client_addr}"
            self.sessions[session_key] = {
                'remote_path': remote_path,
                'chunks': [],
                'total': total_chunks,
                'start_time': time.time()
            }
            print(f"\n[Sync] ====== New Sync Session Started ======")
            print(f"  [Sync] Client: {client_addr}")
            print(f"  [Sync] Target Remote Path: '{remote_path}'")
            print(f"  [Sync] Total chunks expected: {total_chunks}")
            return True
        except Exception as e:
            print(f"  [Sync] Error starting sync session: {e}")
            return False
            
    def add_chunk(self, client_addr: tuple, chunk_num: int, chunk_data: str) -> bool:
        """Add a chunk to the client's sync session."""
        session_key = f"sync-{client_addr}"
        session = self.sessions.get(session_key)
        
        if not session:
            print(f"  [Sync] Error: No active session found for {client_addr}")
            return False
            
        try:
            session['chunks'].append(chunk_data)
            print(f"  [Sync] Received chunk {chunk_num}/{session['total']} from {client_addr}")
            print(f"  [Sync] Chunk size: {len(chunk_data)} bytes")
            return True
        except Exception as e:
            print(f"  [Sync] Error adding chunk: {e}")
            return False
            
    def process_manifest(self, client_addr: tuple) -> tuple[bool, str]:
        """Process the complete manifest and determine required actions."""
        session_key = f"sync-{client_addr}"
        session = self.sessions.get(session_key)
        
        if not session:
            return False, "ERR_NO_SYNC_SESSION"
            
        try:
            full_manifest_str = "".join(session['chunks'])
            client_manifest = json.loads(full_manifest_str)
            print(f"\nDebug: Client manifest size: {len(client_manifest)} items")
            
            # 1. 从会话中获取 remote_path
            remote_path_str = session['remote_path']
            
            # 2. 构建目标目录的完整、绝对路径
            target_dir = (self.config.base_dir / remote_path_str).resolve()

            # 3. !!! 安全检查: 确保目标目录在服务器根目录下 !!!
            if not str(target_dir).startswith(str(self.config.base_dir.resolve())):
                print(f"[SECURITY] Client {client_addr} attempted directory traversal: '{remote_path_str}'")
                return False, "ERR_INVALID_PATH"

            # 4. 如果目录不存在，则创建它
            target_dir.mkdir(parents=True, exist_ok=True)

            # 5. 在指定的目标目录生成服务器清单
            server_manifest = generate_md5_manifest(target_dir) # <-- 修改: 使用目标目录
            print(f"Debug: Server manifest size: {len(server_manifest)} items for path '{target_dir}'")

            # 后续的比较逻辑完全不变...
            client_items = set(client_manifest.keys())
            server_items = set(server_manifest.keys())
            items_to_delete = server_items - client_items
            files_to_request = []
            
            print(f"\n[Sync] ====== File Changes for '{remote_path_str}' ======") # <-- 增强日志
            print(f"  [Sync] Items to delete: {len(items_to_delete)}")
            
            for path in sorted(set(client_items) | server_items):
                client_md5 = client_manifest.get(path)
                server_md5 = server_manifest.get(path)
                
                if path not in server_manifest:
                    print(f"  [Sync] New file: {path}")
                    files_to_request.append(path)
                elif client_md5 != "__DIR__" and server_md5 != "__DIR__" and client_md5 != server_md5:
                    print(f"  [Sync] Modified file: {path}")
                    files_to_request.append(path)
            
            # 将目标目录传递给删除函数
            self._delete_files(items_to_delete, target_dir) # <-- 修改: 传递目标目录
            
            # 后续的返回逻辑完全不变...
            if files_to_request:
                response_data = {
                    "status": "NEEDS_FILES",
                    "files": files_to_request
                }
                payload_str = json.dumps(response_data)
                # Store chunks in session for client to fetch
                session['response_chunks'] = [payload_str[i:i+1024] for i in range(0, len(payload_str), 1024)]
                num_chunks = len(session['response_chunks'])
                return True, f"NEEDS_FILES_READY {num_chunks}"
            else:
                session['response_chunks'] = []
                return True, "SYNC_OK_NO_CHANGES"
            
        except Exception as e:
            print(f"Error processing manifest: {e}")
            return False, f"ERR_PROCESSING_MANIFEST: {str(e)}"
            
    def get_response_chunk(self, client_addr: tuple, chunk_index: int) -> tuple[bool, str]:
        """Get a specific response chunk for a client."""
        session_key = f"sync-{client_addr}"
        session = self.sessions.get(session_key)
        
        if not session or 'response_chunks' not in session:
            return False, "ERR_NO_SYNC_SESSION_DATA"
            
        try:
            chunk_data = session['response_chunks'][chunk_index]
            # If this is the last chunk, clean up the session
            if chunk_index == len(session['response_chunks']) - 1:
                print(f"    [Sync] Client {client_addr} has fetched all response chunks. Cleaning up session.")
                self.sessions.pop(session_key, None)
            return True, chunk_data
        except IndexError:
            return False, "ERR_INVALID_CHUNK_INDEX"
            
    def _delete_files(self, items_to_delete: set, base_delete_path: Path) -> None:
        """在指定的基础路径下删除不再需要的文件和空目录。"""
        if not items_to_delete:
            return
            
        sorted_items = sorted(items_to_delete, key=lambda x: len(x.split('/')), reverse=True)
        
        for path in sorted_items:
            full_path = base_delete_path / path
            try:
                if full_path.is_file():
                    full_path.unlink()
                    print(f"  [Sync] Deleted: {path}")
                elif full_path.is_dir():
                    is_empty = not any(full_path.iterdir())
                    if is_empty:
                        full_path.rmdir()
                        print(f"  [Sync] Deleted empty directory: {path}/")
                    else:
                        print(f"  [Sync] Keeping directory: {path}/ (contains files not managed by this client)")
            except Exception as e:
                print(f"  [Sync] Failed to delete {path}: {e}")

class FileServer:
    """Main file server class"""
    def __init__(self, config: ServerConfig):
        self.config = config
        self.file_handler = FileTransferHandler(config)
        self.folder_handler = FolderHandler(config)
        self.sync_handler = SyncHandler(config)  # Add sync handler
        self.client_paths = {}
        self.server_sock = None
        self.is_syncing = False  # <-- 新增：一个简单的布尔标志

    def start(self) -> None:
        """Start the server"""
        self.config.base_dir.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Server files directory is ready at: {self.config.base_dir}")

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_sock.bind((self.config.host, self.config.default_port))
        print(f"[*] Server listening on {self.config.host or '0.0.0.0'}:{self.config.default_port}")

        self._main_loop()

    def _main_loop(self) -> None:
        """Main server loop"""
        while True:
            try:
                print("\n======================================================")
                message_bytes, client_addr = self.server_sock.recvfrom(self.config.buffer_size)
                self._handle_client_request(message_bytes, client_addr)
            except Exception as e:
                print(f"\n!!! [FATAL] An error occurred in the main loop: {e}")

    def _handle_client_request(self, message_bytes: bytes, client_addr: tuple) -> None:
        """Handle incoming client request"""
        message_str = message_bytes.decode('utf-8')
        parts = message_str.split('\n', 1)
        command_line = parts[0]
        payload = parts[1] if len(parts) > 1 else ""
        
        # --- 新增的、极简的锁定检查 ---
        # 1. 检查服务器是否正在同步
        # 2. 并且检查进来的命令不是一个同步流程中的后续命令
        allowed_sync_commands = ("SYNC_CHUNK", "SYNC_FINISH", "GET_SYNC_CHUNK")
        if self.is_syncing and not command_line.startswith(allowed_sync_commands):
            # 3. 如果是其他命令 (如 UPLOAD, DOWNLOAD, LIST_FILES, 或一个新的 SYNC_START)，则拒绝
            rejection_message = b"server syncing , plz wait"
            print(f"[REJECT] Request '{command_line}' from {client_addr} rejected. Server is syncing.")
            self.server_sock.sendto(rejection_message, client_addr)
            return  # 直接返回，不处理该请求
        # --- 检查结束 ---
        
        print(f"[Main Port] Request from {client_addr}: '{command_line}'")
        current_client_path = self.client_paths.get(client_addr, self.config.base_dir)

        if command_line.startswith("CD "):
            self._handle_cd_command(command_line, client_addr, current_client_path)
        elif command_line == "LIST_FILES":
            self._handle_list_command(client_addr, current_client_path)
        elif command_line.startswith("UPLOAD "):
            self._handle_upload_command(command_line, client_addr, current_client_path)
        elif command_line.startswith("DOWNLOAD "):
            self._handle_download_command(command_line, client_addr, current_client_path)
        elif command_line.startswith("SYNC_START "):
            self._handle_sync_start(command_line, client_addr)
        elif command_line.startswith("SYNC_CHUNK "):
            self._handle_sync_chunk(command_line, payload, client_addr)
        elif command_line == "SYNC_FINISH":
            self._handle_sync_finish(client_addr)
        elif command_line.startswith("GET_SYNC_CHUNK "):
            self._handle_get_sync_chunk(command_line, client_addr)
        elif command_line.startswith("SUPLOAD_STRUCTURE "):
            self._handle_supload_structure(command_line, payload, client_addr, current_client_path)
        elif command_line.startswith("SUPLOAD_FILE "):
            self._handle_supload_file(command_line, client_addr)
        elif command_line == "SUPLOAD_COMPLETE":
            self._handle_supload_complete(client_addr)
        elif command_line == "KILL_SERVER_FILES":
            self._handle_kill_command(client_addr)
        else:
            self.server_sock.sendto(b"ERR_UNKNOWN_COMMAND", client_addr)

    def _handle_cd_command(self, command_line: str, client_addr: tuple, current_client_path: Path) -> None:
        """Handle CD command"""
        target_dir = command_line.split(" ", 1)[1]
        if target_dir == "..":
            new_path = current_client_path.parent if current_client_path != self.config.base_dir else self.config.base_dir
        else:
            new_path = current_client_path / target_dir
        
        real_new_path = new_path.resolve()
        if real_new_path.is_dir() and str(real_new_path).startswith(str(self.config.base_dir)):
            self.client_paths[client_addr] = real_new_path
            response = f"CD_OK Now in /{real_new_path.relative_to(self.config.base_dir) or '.'}"
        else:
            response = "CD_ERR Directory not found or invalid."
        self.server_sock.sendto(response.encode('utf-8'), client_addr)

    def _handle_list_command(self, client_addr: tuple, current_client_path: Path) -> None:
        """Handle LIST_FILES command"""
        entries = list(current_client_path.iterdir())
        files = [f.name for f in entries if f.is_file()]
        dirs = [f"{d.name}/" for d in entries if d.is_dir()]
        response = "OK " + " ".join(dirs + files)
        self.server_sock.sendto(response.encode('utf-8'), client_addr)

    def _handle_upload_command(self, command_line: str, client_addr: tuple, current_client_path: Path) -> None:
        """Handle UPLOAD command"""
        filename = command_line.split(' ', 1)[1]
        file_path = current_client_path / filename
        self.server_sock.sendto(b"UPLOAD_READY", client_addr)
        self.file_handler.receive_file_data(self.server_sock, client_addr, file_path)

    def _handle_download_command(self, command_line: str, client_addr: tuple, current_client_path: Path) -> None:
        """Handle DOWNLOAD command"""
        filename = command_line.split(' ', 1)[1]
        file_path = current_client_path / filename
        if file_path.is_file():
            data_port = self.config.base_data_port + threading.active_count()
            response = f"OK {filename} SIZE {file_path.stat().st_size} PORT {data_port}"
            self.server_sock.sendto(response.encode('utf-8'), client_addr)
            threading.Thread(
                target=self.file_handler.handle_file_transfer,
                args=(filename, data_port, current_client_path)
            ).start()
        else:
            self.server_sock.sendto(f"ERR {filename} NOT_FOUND".encode('utf-8'), client_addr)

    def _handle_sync_start(self, command_line: str, client_addr: tuple) -> None:
        """Handle SYNC_START <remote_path> <num_chunks> command."""
        # 检查是否已有另一个同步在进行
        if self.is_syncing:
            print(f"[REJECT] New sync from {client_addr} rejected. Server is already syncing.")
            self.server_sock.sendto(b"server syncing , plz wait", client_addr)
            return

        # 设置同步状态为 True
        self.is_syncing = True
        print(f"[LOCK] Server is now locked for SYNC operation by {client_addr}.")

        try:
            parts = command_line.split(' ', 2) # 最多分割两次
            remote_path = parts[1]
            total_chunks = int(parts[2])

            # 调用新的 start_sync_session 方法
            if self.sync_handler.start_sync_session(client_addr, remote_path, total_chunks):
                self.server_sock.sendto(b"SYNC_READY", client_addr)
            else:
                self.server_sock.sendto(b"ERR_INVALID_START_COMMAND", client_addr)
        except (ValueError, IndexError):
            print(f"  [Sync] Error: Invalid start command from {client_addr}: {command_line}")
            self.server_sock.sendto(b"ERR_INVALID_START_COMMAND", client_addr)

    def _handle_sync_chunk(self, command_line: str, payload: str, client_addr: tuple) -> None:
        """Handle SYNC_CHUNK command."""
        try:
            chunk_num_str = command_line.split()[1].split('/')[0]
            chunk_num = int(chunk_num_str)
            
            if self.sync_handler.add_chunk(client_addr, chunk_num, payload):
                self.server_sock.sendto(f"ACK_CHUNK {chunk_num}".encode('utf-8'), client_addr)
            else:
                self.server_sock.sendto(b"ERR_NO_SYNC_SESSION", client_addr)
        except (ValueError, IndexError):
            print(f"  [Sync] Error: Invalid chunk command from {client_addr}: {command_line}")
            self.server_sock.sendto(b"ERR_INVALID_CHUNK_COMMAND", client_addr)

    def _handle_sync_finish(self, client_addr: tuple) -> None:
        """Handle SYNC_FINISH command and ensure server unlocks."""
        try:
            success, response = self.sync_handler.process_manifest(client_addr)
            self.server_sock.sendto(response.encode('utf-8'), client_addr)
        finally:
            # 无论成功与否，最后都必须将标志设回 False
            self.is_syncing = False
            print(f"[UNLOCK] Server is now unlocked. Sync operation for {client_addr} has finished.")

    def _handle_get_sync_chunk(self, command_line: str, client_addr: tuple) -> None:
        """Handle GET_SYNC_CHUNK command."""
        try:
            chunk_index = int(command_line.split(' ', 1)[1])
            success, response = self.sync_handler.get_response_chunk(client_addr, chunk_index)
            self.server_sock.sendto(response.encode('utf-8'), client_addr)
        except (IndexError, ValueError) as e:
            print(f"!!! [Sync] Invalid chunk request from {client_addr}: {command_line}. Error: {e}")
            self.server_sock.sendto(b"ERR_INVALID_CHUNK_REQUEST", client_addr)

    def _handle_supload_structure(self, command_line: str, payload: str, client_addr: tuple, current_client_path: Path) -> None:
        """Handle SUPLOAD_STRUCTURE command"""
        root_folder_name = command_line.split(' ', 1)[1]
        if self.folder_handler.create_folder_structure(root_folder_name, current_client_path, payload, client_addr):
            self.server_sock.sendto(b"STRUCTURE_OK", client_addr)
        else:
            self.server_sock.sendto(b"STRUCTURE_ERR", client_addr)

    def _handle_supload_file(self, command_line: str, client_addr: tuple) -> None:
        """Handle SUPLOAD_FILE command"""
        if not self.folder_handler.is_session_valid(client_addr):
            self.server_sock.sendto(b"ERR_NO_SUPLOAD_SESSION", client_addr)
            return

        relative_file_path = command_line.split(' ', 1)[1]
        full_save_path = self.folder_handler.get_upload_path(client_addr, relative_file_path)
        
        if full_save_path:
            self.server_sock.sendto(b"FILE_READY", client_addr)
            self.file_handler.receive_file_data(self.server_sock, client_addr, full_save_path)
        else:
            self.server_sock.sendto(b"ERR_INVALID_PATH", client_addr)

    def _handle_supload_complete(self, client_addr: tuple) -> None:
        """Handle SUPLOAD_COMPLETE command"""
        self.folder_handler.cleanup_session(client_addr)
        self.server_sock.sendto(b"SUPLOAD_OK", client_addr)

    def _handle_kill_command(self, client_addr: tuple) -> None:
        """Handle KILL_SERVER_FILES command"""
        shutil.rmtree(self.config.base_dir)
        self.config.base_dir.mkdir(parents=True, exist_ok=True)
        self.server_sock.sendto(b"KILL_OK All files and directories deleted successfully.", client_addr)

if __name__ == "__main__":
    # Create server configuration
    config = ServerConfig.from_args()
    
    # Create and start server
    server = FileServer(config)
    server.start()