import socket
import os
import base64
import time
import sys
from pathlib import Path
import hashlib # <-- 新增
import json    # <-- 新增


CONFIG_FILE = "sync_config.json"

def load_sync_config() -> list:
    """从配置文件加载同步对。"""
    if not Path(CONFIG_FILE).is_file():
        return []
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError):
        print(f"[WARNING] Could not parse {CONFIG_FILE}. Starting with empty config.")
        return []

def save_sync_config(config: list):
    """将同步对保存到配置文件。"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

# Create client_files directory at program start
Path("client_files").mkdir(exist_ok=True)

def calculate_md5(file_path: Path) -> str:
    """计算文件的 MD5 哈希值"""
    hash_md5 = hashlib.md5()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def generate_md5_manifest(directory: str) -> dict:
    """生成包含 {路径: MD5值} 的字典清单"""
    manifest = {}
    base_dir = Path(directory)
    try:
        for item in base_dir.rglob('*'):
            if item.is_file():
                relative_path = str(item.relative_to(base_dir)).replace(os.path.sep, '/')
                manifest[relative_path] = calculate_md5(item)
                print(f"Debug: Added to client manifest - {relative_path}: {manifest[relative_path]}")
    except Exception as e:
        print(f"Error generating client manifest: {e}")
    return manifest

def sendAndReceive(sock, message, server_address, timeout=1.0, max_retries=5):
    for attempt in range(max_retries):
        try:
            sock.settimeout(timeout)
            sock.sendto(message.encode('utf-8'), server_address)
            
            response_bytes, addr = sock.recvfrom(4096)
            return response_bytes.decode('utf-8'), addr

        except socket.timeout:
            if attempt < max_retries - 1:
                print(f"*** Timeout after {timeout:.1f}s. Retrying... ({attempt + 1}/{max_retries}) ***")
                continue
            else:
                raise Exception(f"Server not responding after {max_retries} attempts.")

def _perform_upload(sock, server_address, local_path: Path, remote_path: str, verbose: bool = True) -> bool:
    try:
        file_size = local_path.stat().st_size
        
        # 1. 发送 UPLOAD 命令，告知服务器准备接收
        response_str, _ = sendAndReceive(sock, f"UPLOAD {remote_path}", server_address)
        if response_str != "UPLOAD_READY":
            if verbose: print(f"\n[ERROR] Server not ready for upload: {response_str}")
            return False

        # 2. 开始分块传输
        with local_path.open("rb") as f:
            bytes_sent = 0
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                
                # 直接在这里发送数据块，不再需要 transfer_file_chunk
                encoded_chunk = base64.b64encode(chunk).decode('utf-8')
                data_message = f"DATA {encoded_chunk}"
                response_str, _ = sendAndReceive(sock, data_message, server_address)
                
                if response_str != "ACK_DATA":
                    if verbose: print(f"\n[ERROR] Failed to get ACK for a chunk.")
                    return False

                bytes_sent += len(chunk)
                if verbose:
                    progress = (bytes_sent / file_size) * 100 if file_size > 0 else 100
                    print(f"\rUpload progress: {progress:.2f}% ({bytes_sent}/{file_size} bytes)", end='')

        # 3. 发送上传完成信号
        response_str, _ = sendAndReceive(sock, "UPLOAD_DONE", server_address)
        if response_str == "UPLOAD_COMPLETE":
            if verbose: print(f"\n[SUCCESS] File '{remote_path}' uploaded successfully!")
            return True
        else:
            if verbose: print(f"\n[WARNING] Unexpected final response: {response_str}")
            return False

    except Exception as e:
        if verbose: print(f"\n[ERROR] Upload failed: {str(e)}")
        return False

def _perform_download(sock, server_address, remote_filename: str, local_path: Path) -> bool:
    try:
        # 1. 发送 DOWNLOAD 命令 (此处的 socket 是主命令 socket)
        # 注意: 你的原逻辑是新开一个端口，这里为了简化，我们假设仍在同一个 socket 上通信
        # 如果必须在新端口，则此函数需要接收一个新的 data_sock
        response_str, _ = sendAndReceive(sock, f"DOWNLOAD {remote_filename}", server_address)
        if response_str != "DOWNLOAD_READY":
            print(f"[ERROR] Server not ready for download: {response_str}")
            return False
            
        # 2. 开始分块接收
        with local_path.open("wb") as f:
            bytes_received = 0
            while True:
                response_str, _ = sendAndReceive(sock, "GET_CHUNK", server_address)
                if response_str == "TRANSFER_COMPLETE":
                    break
                if not response_str.startswith("DATA "):
                    print("\n[ERROR] Invalid data chunk received from server.")
                    return False
                    
                data = base64.b64decode(response_str[5:])
                f.write(data)
                bytes_received += len(data)
                print(f"\rDownload progress: {bytes_received} bytes received", end='')
        
        print(f"\n[SUCCESS] File '{remote_filename}' downloaded successfully to '{local_path}'!")
        return True

    except Exception as e:
        print(f"\n[ERROR] Download failed: {str(e)}")
        return False

def handle_upload(sock, server_address, command_input):
    """Handles the user 'upload' command by resolving paths and calling the core upload function."""
    input_path_str = command_input.strip().strip('\'"')

    local_path_to_read = None
    path_for_server = None

    path_in_client_files = Path("client_files") / input_path_str
    if path_in_client_files.is_file():
        local_path_to_read = path_in_client_files
        path_for_server = input_path_str
    elif Path(input_path_str).is_file():
        local_path_to_read = Path(input_path_str)
        path_for_server = local_path_to_read.name
    else:
        print(f"\n[ERROR] File not found at '{path_in_client_files}' or '{input_path_str}'.")
        return

    path_for_server_norm = str(path_for_server).replace(os.path.sep, '/')

    # 直接调用核心上传函数，并要求详细输出
    _perform_upload(sock, server_address, local_path_to_read, path_for_server_norm, verbose=True)

def handle_super_upload(sock, server_address, local_folder_path):
    """Handle folder upload with simplified logic."""
    folder_path = Path(local_folder_path.strip().strip('\'"'))
    if not folder_path.is_dir():
        print(f"\n[ERROR] '{folder_path}' is not a valid directory.")
        return

    try:
        # Get all files recursively
        files = [f for f in folder_path.rglob("*") if f.is_file()]
        if not files:
            print(f"\n[ERROR] No files found in '{folder_path}'")
            return

        # Create directory structure
        dirs = [str(d.relative_to(folder_path)).replace("\\", "/") 
                for d in folder_path.rglob("*") if d.is_dir()]
        
        structure_payload = f"SUPLOAD_STRUCTURE {folder_path.name}\n" + "\n".join(dirs)
        response_str, _ = sendAndReceive(sock, structure_payload, server_address)
        if response_str != "STRUCTURE_OK":
            print(f"\n[ERROR] Failed to create directory structure: {response_str}")
            return

        # Upload each file
        for i, file_path in enumerate(files, 1):
            rel_path = str(file_path.relative_to(folder_path)).replace("\\", "/")
            print(f"\n({i}/{len(files)}) Uploading: {rel_path}")
            
            response_str, _ = sendAndReceive(sock, f"SUPLOAD_FILE {rel_path}", server_address)
            if response_str != "FILE_READY":
                print(f"[WARNING] Server not ready for '{rel_path}', skipping.")
                continue

            # _perform_upload 现在处理完整的上传握手，无需额外操作
            # 我们给它传递 verbose=False 来减少输出
            if not _perform_upload(sock, server_address, file_path, rel_path, verbose=False):
                 print(f"[ERROR] Failed to upload '{rel_path}'")

        # Complete the upload
        response_str, _ = sendAndReceive(sock, "SUPLOAD_COMPLETE", server_address)
        if response_str == "SUPLOAD_OK":
            print(f"\n[SUCCESS] Folder '{folder_path.name}' uploaded completely!")
        else:
            print(f"\n[WARNING] Unexpected final response: {response_str}")

    except Exception as e:
        print(f"\n[ERROR] Upload failed: {str(e)}")

class SyncManager:
    """Manages file synchronization between client and server."""
    
    def __init__(self, sock, server_address, local_path: str, remote_path: str):
        self.sock = sock
        self.server_address = server_address
        self.local_path = Path(local_path)   # <-- 新增: 本地同步路径
        self.remote_path = remote_path       # <-- 新增: 远程同步路径
        self.chunk_size = 1024
        self.sync_interval = 3  # seconds
        
    def generate_md5_manifest(self, directory: str) -> dict:
        """Generate a manifest by calling the global utility function."""
        return generate_md5_manifest(directory)

    def transfer_manifest(self, manifest: dict) -> bool:
        """Transfer the manifest to server in chunks."""
        try:
            manifest_payload = json.dumps(manifest)
            chunks = [manifest_payload[i:i+self.chunk_size] 
                     for i in range(0, len(manifest_payload), self.chunk_size)]
            num_chunks = len(chunks)

            # 使用 self.remote_path 告知服务器要同步哪个目录
            response, _ = sendAndReceive(self.sock, f"SYNC_START {self.remote_path} {num_chunks}", self.server_address)
            if response != "SYNC_READY":
                raise Exception(f"Server not ready for sync. Response: {response}")

            # Transfer chunks
            for i, chunk in enumerate(chunks):
                ack_response, _ = sendAndReceive(
                    self.sock, 
                    f"SYNC_CHUNK {i}/{num_chunks}\n{chunk}", 
                    self.server_address
                )
                if ack_response != f"ACK_CHUNK {i}":
                    raise Exception(f"Manifest chunk {i} upload failed. ACK not received.")

            return True
        except Exception as e:
            print(f"Error transferring manifest: {e}")
            return False

    def process_server_response(self, response: str) -> None:
        """Process server's response to manifest and handle file uploads."""
        # Case 1: Files are already in sync
        if response == "SYNC_OK_NO_CHANGES":
            print(" -> All files are in sync.")
            return

        # Case 2: Server has prepared data chunks, client needs to fetch them
        if response.startswith("NEEDS_FILES_READY"):
            try:
                parts = response.split()
                if len(parts) != 2:
                    raise ValueError("Invalid READY response format")
                
                num_chunks = int(parts[1])
                print(f" -> Server has {num_chunks} data chunk(s). Fetching...")

                chunks = []
                for i in range(num_chunks):
                    # Use existing sendAndReceive for reliable chunk fetching
                    command = f"GET_SYNC_CHUNK {i}"
                    chunk_data, _ = sendAndReceive(self.sock, command, self.server_address, timeout=5.0)
                    chunks.append(chunk_data)
                    print(f"\r -> Receiving file list... {i+1}/{num_chunks}", end="")
                
                print()  # New line after progress
                json_payload = "".join(chunks)

                # Parse JSON and handle file uploads
                response_data = json.loads(json_payload)
                if 'files' not in response_data:
                    raise ValueError("Invalid JSON format: missing 'files' field")
                
                files_to_upload = response_data['files']
                if not isinstance(files_to_upload, list):
                    raise ValueError("Expected list of files")
                
                if files_to_upload:
                    print(f" -> Server needs {len(files_to_upload)} file(s). Starting sync upload...")
                    for file_path_str in files_to_upload:
                        # 使用 self.local_path 作为基础路径，而不是写死的 "client_files"
                        local_path = self.local_path / file_path_str
                        if local_path.is_file():
                            print(f"    - Syncing '{file_path_str}'...", end='')
                            # 调用核心上传函数，但设置 verbose=False 来禁止详细输出
                            success = _perform_upload(self.sock, self.server_address, local_path, file_path_str, verbose=False)
                            print(" OK" if success else " FAILED")
                        else:
                            print(f"    - Skipping '{file_path_str}': Not found locally.")
                else:
                    print(" -> All files are in sync.")
            except Exception as e:
                print(f"\n[ERROR] Failed to process server's sync response: {e}")
                print(f"Raw response: {response}")
        else:
            print(f"\n[WARNING] Received unexpected response from server: {response}")

    def sync_cycle(self) -> bool:
        """为 self.local_path 和 self.remote_path 执行一个同步周期。"""
        try:
            # 打印当前正在同步的路径对
            print(f"\n--- Syncing Local: '{self.local_path}' <==> Server: '{self.remote_path}' ---")

            if not self.local_path.is_dir():
                print(f"[ERROR] Local directory '{self.local_path}' not found or is not a directory. Skipping.")
                return False

            print(" -> Step 1/3: Generating local MD5 manifest...")
            # 使用 self.local_path 来生成清单
            manifest = self.generate_md5_manifest(str(self.local_path))
            
            # 后续逻辑与原来相同...
            print(" -> Step 2/3: Transferring manifest to server...")
            if not self.transfer_manifest(manifest):
                return False

            print(" -> Step 3/3: Processing server's file request list...")
            response, _ = sendAndReceive(self.sock, "SYNC_FINISH", self.server_address)
            self.process_server_response(response)

            print("\n[+] Sync cycle completed successfully.")
            print("------------------------------------------------------------")
            return True
            
        except Exception as e:
            print(f"\n[ERROR] An error occurred during sync cycle: {e}")
            return False

    def start_sync_mode(self):
        """为所有在配置文件中的项启动持续同步模式。"""
        print("\n[AUTO SYNC MODE ACTIVATED]")
        print("Client will now sync ALL configured pairs every cycle.")
        print("按下Enter键退出sync模式。")
        
        while True:
            try:
                config = load_sync_config()
                if not config:
                    print("No sync pairs configured. Exiting auto-sync mode.")
                    break

                print(f"\n======= Starting New Auto-Sync Run ({time.ctime()}) =======")
                for item in config:
                    # 动态地更新实例的路径，然后运行同步周期
                    self.local_path = Path(item['local_path'])
                    self.remote_path = item['remote_path']
                    self.sync_cycle()
                print(f"======= Auto-Sync Run Finished =======")

                # Countdown to next sync
                for i in range(self.sync_interval * len(config), 0, -1): # 等待时间可以适当延长
                    print(f'\rNext run in {i} seconds...  ', end='')
                    time.sleep(1)
                print('\r' + ' ' * 60 + '\r', end='')
                
                # 退出检测逻辑保持不变
                import sys, select
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    _ = sys.stdin.readline()
                    print("\n[SYNC MODE DEACTIVATED] (检测到Enter) Returning to command menu.")
                    break
            except Exception as e:
                print(f"\n[ERROR] An error occurred during auto-sync loop: {e}")
                print(f"Waiting {self.sync_interval} seconds before retrying...")
                time.sleep(self.sync_interval)

def download_file(filename, server_host, server_info):
    """Handle file download by creating a new data socket and calling the core download function."""
    _file_size, data_port = server_info
    server_data_address = (server_host, data_port)
    local_file_path = Path("client_files") / Path(filename).name

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as data_sock:
        _perform_download(data_sock, server_data_address, filename, local_file_path)

def parse_command_line_args():
    """
    Parse command line arguments for server connection.
    
    Returns:
        tuple: (server_host, server_port) or (None, default_port)
    """
    default_port = 51234
    
    if len(sys.argv) == 3:
        try:
            return sys.argv[1], int(sys.argv[2])
        except ValueError:
            print(f"Error: Invalid port '{sys.argv[2]}'. Port must be a number.")
            sys.exit(1)
    elif len(sys.argv) == 1:
        return None, default_port
    else:
        print("Usage: python3 client.py [hostname] [port]")
        print("Or run without arguments for interactive mode.")
        sys.exit(1)

def get_server_address():
    server_host, server_port = parse_command_line_args()
    
    if server_host is None:
        user_input = input("Enter server host (press Enter or type 'local' for localhost): ").strip()
        server_host = 'localhost' if user_input.lower() in ('local', '') else user_input
        print(f"[INFO] Server address set to: {server_host}:{server_port}")
    
    return server_host, server_port

def display_server_files(sock, server_address):

    try:
        response_str, _ = sendAndReceive(sock, "LIST_FILES", server_address)
        if response_str.startswith("OK"):
            files = response_str.split()[1:]
            print("\nAvailable entries on server:")
            print(" ".join(files) if files else "(empty)")
            print("-" * 50)
            return files
        else:
            print("Error: Could not get file list from server")
            return []
    except Exception as e:
        print(f"Error getting file list: {str(e)}")
        return []

def display_command_menu():
    """Display the command menu to the user."""
    return input("""
    *！COMMAND MENU ! ^^^^^check the available entries on server^^^^
    ********************************************
    * sync list                    - Show all configured sync pairs
    * sync add <local> <remote>    - Add a new folder pair to sync 
    [WARNING: Never map different local folders (local_path) to a single remote folder (remote_path)]
    * sync remove <id>             - Remove a sync pair by its ID
    * sync run                     - Run a one-time sync for all pairs
    * sync auto                    - Start continuous automatic syncing
    ********************************************
    * <filename>                   - Download a file by entering its name
    * all                          - Download all files in the current directory
    * upload <filename> or <path>  - Upload a file to the server
    * supload <folder> or <path>   - Upload an entire folder to the server
    * cd <folder>                  - Change to the specified directory (e.g., cd my_files)
    * cd ..                        - Go back to the parent directory
    * kill                         - kill every files on server
    * (press enter)                - Exit the client

    Enter command: """)

def handle_sync_subcommands(sock, server_address, args):
    """处理所有 'sync' 子命令，如 list, add, run。"""
    if not args:
        print("\n[ERROR] Sync command requires a subcommand. Use 'sync list' to see options.")
        return

    subcommand = args[0].lower()
    config = load_sync_config()

    if subcommand == 'list':
        if not config:
            print("\nNo sync pairs configured. Use 'sync add <local_path> <remote_path>' to add one.")
            return
        print("\n--- Configured Sync Pairs ---")
        for item in sorted(config, key=lambda x: x['id']):
            print(f"  ID: {item['id']:<3} Local: '{item['local_path']}'  ==>  Remote: '{item['remote_path']}'")
        print("-----------------------------")

    elif subcommand == 'add' and len(args) == 3:
        local_path, remote_path = args[1], args[2]
        if not Path(local_path).is_dir():
            print(f"\n[ERROR] Local path '{local_path}' is not a valid directory.")
            return
        new_id = max([item['id'] for item in config] + [0]) + 1
        config.append({"id": new_id, "local_path": local_path, "remote_path": remote_path})
        save_sync_config(config)
        print(f"\n[SUCCESS] Added sync pair (ID: {new_id}).")

    elif subcommand == 'remove' and len(args) == 2:
        try:
            remove_id = int(args[1])
            new_config = [item for item in config if item['id'] != remove_id]
            if len(new_config) == len(config):
                print(f"\n[ERROR] No sync pair found with ID: {remove_id}")
            else:
                save_sync_config(new_config)
                print(f"\n[SUCCESS] Removed sync pair with ID: {remove_id}")
        except ValueError:
            print("\n[ERROR] Please provide a valid numeric ID to remove.")

    elif subcommand == 'run':
        if not config:
            print("\nNo sync pairs to run.")
            return
        print("\nStarting manual sync run...")
        for item in config:
            # 为每个同步任务创建一个临时的 SyncManager 实例并运行
            sync_manager = SyncManager(sock, server_address, item['local_path'], item['remote_path'])
            sync_manager.sync_cycle()

    elif subcommand == 'auto':
        # 创建一个 SyncManager 实例来启动自动同步模式
        # 初始路径不重要，因为会在循环中被覆盖
        sync_manager = SyncManager(sock, server_address, "", "")
        sync_manager.start_sync_mode()
        
    else:
        print(f"\n[ERROR] Unknown sync subcommand or incorrect arguments: '{' '.join(args)}'")
        print("Usage: sync <list|add|remove|run|auto>")

def handle_command(sock, server_address, command, files, server_host):
    if not command:
        return False
        
    parts = command.split() # 不转小写，以保留路径的大小写
    base_command = parts[0].lower()

    if base_command == 'cd':
        handle_cd_command(sock, server_address, command)
    elif base_command == 'upload':
        handle_upload(sock, server_address, command.split(' ', 1)[1])
    elif base_command == 'supload':
        handle_super_upload(sock, server_address, command.split(' ', 1)[1])
    elif base_command == 'sync':
        # 将参数传递给新的子命令处理器
        handle_sync_subcommands(sock, server_address, parts[1:])
    elif base_command == 'kill':
        handle_kill_command(sock, server_address)
    elif base_command == 'all':
        handle_all_command(sock, server_address, files, server_host)
    else:
        handle_single_download(sock, server_address, command, server_host)
    
    return True

def handle_cd_command(sock, server_address, command):
    """Handle directory change command."""
    command_to_send = "CD " + command.split(' ', 1)[1]
    try:
        response_str, _ = sendAndReceive(sock, command_to_send, server_address)
        print(f"Server: {response_str}")
    except Exception as e:
        print(f"\n[ERROR] Failed to send cd command: {str(e)}")

def handle_kill_command(sock, server_address):
    """Handle kill command to delete all server files."""
    try:
        response_str, _ = sendAndReceive(sock, "KILL_SERVER_FILES", server_address)
        if response_str.startswith("KILL_OK"):
            print("\n[SUCCESS] All files on server have been deleted successfully.")
        elif response_str.startswith("KILL_ERR"):
            print("\n[ERROR] Failed to delete files on server.")
        else:
            print(f"\n[WARNING] Unexpected response from server: {response_str}")
    except Exception as e:
        print(f"\n[ERROR] Failed to send kill command: {str(e)}")

def handle_all_command(sock, server_address, files, server_host):
    """Handle download all files command."""
    if not files:
        print("No files available to download.")
        return
        
    for file_to_download in files:
        if file_to_download.endswith('/'):
            continue
            
        message = f"DOWNLOAD {file_to_download}"
        try:
            response_str, _ = sendAndReceive(sock, message, server_address)
            if response_str.startswith("OK"):
                parts = response_str.split()
                server_info = (int(parts[3]), int(parts[5]))
                download_file(parts[1], server_host, server_info)
            elif response_str.startswith("ERR"):
                print(f"Error: File '{file_to_download}' not found on server")
        except Exception as e:
            print(f"Error during download of '{file_to_download}': {str(e)}")
            continue
    print("\nBatch download completed.")

def handle_single_download(sock, server_address, filename, server_host):
    """Handle single file download command."""
    message = f"DOWNLOAD {filename}"
    try:
        response_str, _ = sendAndReceive(sock, message, server_address)
        if response_str.startswith("OK"):
            parts = response_str.split()
            server_info = (int(parts[3]), int(parts[5]))
            download_file(parts[1], server_host, server_info)
        elif response_str.startswith("ERR"):
            print("Error: File not found on server")
    except Exception as e:
        print(f"Error during initial request: {str(e)}")

def main():
    """Main function to run the client."""
    server_host, server_port = get_server_address()
    server_address = (server_host, server_port)
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    try:
        while True:
            files = display_server_files(client_sock, server_address)
            command = display_command_menu()
            
            if not handle_command(client_sock, server_address, command, files, server_host):
                break
                
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        print("\nClient session finished. Exiting.")
        client_sock.close()


if __name__ == "__main__":
    main()