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
    def from_args(cls, default_port: int) -> 'ServerConfig':
        """Create config from command line arguments"""
        if len(sys.argv) == 1:
            print(f"[INFO] No port provided. Using default port: {default_port}")
            return cls(default_port=default_port)
        elif len(sys.argv) == 2:
            try:
                port = int(sys.argv[1])
                print(f"[INFO] Port specified by user: {port}")
                return cls(default_port=port)
            except ValueError:
                print(f"[ERROR] Invalid port '{sys.argv[1]}'. Port must be a number.")
                sys.exit(1)
        else:
            print("[ERROR] Too many arguments.")
            print("Usage: python3 server.py [port]")
            sys.exit(1)

def get_port_from_args(default_port):
    """
    Get port number from command line arguments.
    - If no arguments provided, returns default port
    - If one valid argument provided, returns that port
    - If invalid or too many arguments, prints error and exits
    """
    if len(sys.argv) == 1:
        print(f"[INFO] No port provided. Using default port: {default_port}")
        return default_port
    elif len(sys.argv) == 2:
        try:
            port = int(sys.argv[1])
            print(f"[INFO] Port specified by user: {port}")
            return port
        except ValueError:
            print(f"[ERROR] Invalid port '{sys.argv[1]}'. Port must be a number.")
            sys.exit(1)
    else:
        print("[ERROR] Too many arguments.")
        print("Usage: python3 server.py [port]")
        sys.exit(1)

### MODIFICATION START: 1. 定义服务器的根目录 ###
# 将根目录定义为一个全局常量，方便引用
SERVER_BASE_DIR = os.path.realpath("serverfile")
### MODIFICATION END ###

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

class FileServer:
    """Main file server class"""
    def __init__(self, config: ServerConfig):
        self.config = config
        self.file_handler = FileTransferHandler(config)
        self.folder_handler = FolderHandler(config)  # Add folder handler
        self.client_paths = {}  # For standard file operations
        self.server_sock = None

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
        """Step 1: Client requests to start a new sync session"""
        try:
            total_chunks = int(command_line.split()[1])
            session_key = f"sync-{client_addr}"
            # Reuse the FolderHandler's sessions dictionary to manage the session
            self.folder_handler.sessions[session_key] = {'chunks': [], 'total': total_chunks}
            print(f"\n[Sync] ====== New Sync Session Started ======")
            print(f"  [Sync] Client: {client_addr}")
            print(f"  [Sync] Total chunks expected: {total_chunks}")
            print(f"  [Sync] Session key: {session_key}")
            self.server_sock.sendto(b"SYNC_READY", client_addr)
        except (ValueError, IndexError):
            print(f"  [Sync] Error: Invalid start command from {client_addr}: {command_line}")
            self.server_sock.sendto(b"ERR_INVALID_START_COMMAND", client_addr)

    def _handle_sync_chunk(self, command_line: str, payload: str, client_addr: tuple) -> None:
        """Step 2: Client sends a manifest data chunk"""
        session_key = f"sync-{client_addr}"
        session = self.folder_handler.sessions.get(session_key)

        if not session:
            print(f"  [Sync] Error: No active session found for {client_addr}")
            self.server_sock.sendto(b"ERR_NO_SYNC_SESSION", client_addr)
        else:
            try:
                chunk_num_str = command_line.split()[1].split('/')[0]
                chunk_num = int(chunk_num_str)
                session['chunks'].append(payload)
                print(f"  [Sync] Received chunk {chunk_num}/{session['total']} from {client_addr}")
                print(f"  [Sync] Chunk size: {len(payload)} bytes")
                self.server_sock.sendto(f"ACK_CHUNK {chunk_num}".encode('utf-8'), client_addr)
            except (ValueError, IndexError):
                print(f"  [Sync] Error: Invalid chunk command from {client_addr}: {command_line}")
                self.server_sock.sendto(b"ERR_INVALID_CHUNK_COMMAND", client_addr)

    def _handle_sync_finish(self, client_addr: tuple) -> None:
        """Step 3: Client notifies that manifest is complete, server starts processing"""
        session_key = f"sync-{client_addr}"
        session = self.folder_handler.sessions.get(session_key)

        if not session:
            self.server_sock.sendto(b"ERR_NO_SYNC_SESSION", client_addr)
            return

        full_manifest_str = "".join(session['chunks'])
        
        try:
            client_manifest = json.loads(full_manifest_str)
            print(f"\nDebug: Client manifest size: {len(client_manifest)} items")
        except json.JSONDecodeError:
            print(f"Error: Failed to parse client manifest JSON")
            del self.folder_handler.sessions[session_key]
            return

        # Note: Sync is based on the server's root directory
        server_manifest = generate_md5_manifest(self.config.base_dir)
        print(f"Debug: Server manifest size: {len(server_manifest)} items")
        
        client_items = set(client_manifest.keys())
        server_items = set(server_manifest.keys())
        
        # 获取需要删除的项目
        items_to_delete = server_items - client_items
        files_to_request = []
        
        print(f"\n[Sync] ====== File Changes ======")
        print(f"  [Sync] Items to delete: {len(items_to_delete)}")
        
        # 打印所有文件路径和MD5值进行比较
        print("\nDebug: File comparison:")
        for path in sorted(set(client_items) | server_items):
            client_md5 = client_manifest.get(path)
            server_md5 = server_manifest.get(path)
            print(f"Path: {path}")
            print(f"  Client MD5: {client_md5}")
            print(f"  Server MD5: {server_md5}")
            
            if path not in server_manifest:
                print(f"  [Sync] New file: {path}")
                files_to_request.append(path)
            elif client_md5 != "__DIR__" and server_md5 != "__DIR__" and client_md5 != server_md5:
                print(f"  [Sync] Modified file: {path}")
                files_to_request.append(path)
        
        # Execute deletions
        if items_to_delete:
            # 首先删除文件，然后删除目录
            # 按路径长度排序，确保先删除深层项目
            sorted_items = sorted(items_to_delete, key=lambda x: len(x.split('/')), reverse=True)
            for path in sorted_items:
                full_path = self.config.base_dir / path
                try:
                    if full_path.is_file():
                        full_path.unlink()
                        print(f"  [Sync] Deleted: {path}")
                    elif full_path.is_dir():
                        # 检查目录是否为空
                        is_empty = not any(full_path.iterdir())
                        if is_empty:
                            full_path.rmdir()
                            print(f"  [Sync] Deleted empty directory: {path}/")
                        else:
                            print(f"  [Sync] Keeping directory: {path}/ (contains files)")
                except Exception as e:
                    print(f"  [Sync] Failed to delete {path}: {e}")
        
        # 修改响应格式为JSON
        if files_to_request:
            response_data = {
                "status": "NEEDS_FILES",
                "files": files_to_request
            }
            response = f"NEEDS_FILES\n{json.dumps(response_data)}"
            print(f"Debug: Requesting {len(files_to_request)} files")
        else:
            response = "SYNC_OK_NO_CHANGES"
            print("Debug: No files need to be updated")
        
        self.server_sock.sendto(response.encode('utf-8'), client_addr)
        
        # Clean up session
        del self.folder_handler.sessions[session_key]

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
    config = ServerConfig.from_args(51234)
    
    # Create and start server
    server = FileServer(config)
    server.start()