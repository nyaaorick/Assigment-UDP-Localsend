import socket
import os
import base64
import time
import sys
from pathlib import Path
import hashlib # <-- 新增
import json    # <-- 新增

# Create client_files directory at program start
Path("client_files").mkdir(exist_ok=True)

# ... import 语句之后 ...

# =================================================================
# --- 新增功能 #1: MD5 清单生成函数 ---
# =================================================================
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
    """
    Send a message to the server and wait for a response with retry mechanism.
    
    Args:
        sock: UDP socket for communication
        message: Message to send
        server_address: Server address tuple (host, port)
        timeout: Timeout in seconds for each attempt
        max_retries: Maximum number of retry attempts
        
    Returns:
        tuple: (response_string, server_address)
        
    Raises:
        Exception: If server doesn't respond after all retries
    """
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


def transfer_file_chunk(sock, server_address, chunk, chunk_size=1024):
    """
    Transfer a single chunk of data with retry mechanism.
    
    Args:
        sock: Socket for communication
        server_address: Server address tuple
        chunk: Data chunk to transfer
        chunk_size: Size of each chunk
        
    Returns:
        bool: True if transfer successful, False otherwise
    """
    try:
        encoded_chunk = base64.b64encode(chunk).decode('utf-8')
        data_message = f"DATA {encoded_chunk}"
        response_str, _ = sendAndReceive(sock, data_message, server_address)
        return response_str == "ACK_DATA"
    except Exception:
        return False

def transfer_file(sock, server_address, file_path, is_upload=True):
    """
    Generic file transfer function for both upload and download.
    
    Args:
        sock: Socket for communication
        server_address: Server address tuple
        file_path: Path to the file
        is_upload: True for upload, False for download
        
    Returns:
        bool: True if transfer successful, False otherwise
    """
    try:
        file_path = Path(file_path)
        if is_upload:
            if not file_path.is_file():
                print(f"[ERROR] File not found: {file_path}")
                return False
                
            file_size = file_path.stat().st_size
            with open(file_path, 'rb') as f:
                bytes_sent = 0
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    if not transfer_file_chunk(sock, server_address, chunk):
                        return False
                    bytes_sent += len(chunk)
                    progress = (bytes_sent / file_size) * 100
                    print(f"\rUpload progress: {progress:.2f}% ({bytes_sent}/{file_size} bytes)", end='')
            return True
            
        else:  # Download
            with open(file_path, 'wb') as f:
                bytes_received = 0
                while True:
                    response_str, _ = sendAndReceive(sock, "GET_CHUNK", server_address)
                    if response_str == "TRANSFER_COMPLETE":
                        break
                    if not response_str.startswith("DATA "):
                        return False
                        
                    data = base64.b64decode(response_str[5:])
                    f.write(data)
                    bytes_received += len(data)
                    print(f"\rDownload progress: {bytes_received} bytes", end='')
            return True
            
    except Exception as e:
        print(f"\n[ERROR] Transfer failed: {str(e)}")
        return False

def handle_upload(sock, server_address, command_input):
    """
    处理文件上传。此版本智能处理路径，能够：
    1. 接受 'data.txt' 这样的简单文件名（在 client_files 中查找）。
    2. 接受 'images/photo.png' 这样的相对路径（由 sync 功能使用）。
    3. 接受 '/Users/me/Desktop/report.pdf' 这样的完整外部路径。
    """
    input_path_str = command_input.strip().strip('\'"')

    # --- 新增的智能路径解析逻辑 ---
    
    local_path_to_read = None
    path_for_server = None

    # 优先级 1: 尝试将输入作为相对于 'client_files' 的路径。
    # 这同时满足了【用例1】和【用例2】。
    path_in_client_files = Path("client_files") / input_path_str
    if path_in_client_files.is_file():
        local_path_to_read = path_in_client_files
        # 发送给服务器的路径就是这个相对路径
        path_for_server = input_path_str
    
    # 优先级 2: 如果在 client_files 中找不到，则尝试将其作为直接路径（可能是绝对路径）。
    # 这满足了【用例3】。
    elif Path(input_path_str).is_file():
        local_path_to_read = Path(input_path_str)
        # 对于外部文件，我们只把文件名本身传到服务器的当前目录
        path_for_server = local_path_to_read.name
    
    else:
        print(f"\n[ERROR] File not found. Neither '{path_in_client_files}' nor '{input_path_str}' is a valid file.")
        return
        
    # --- 路径解析逻辑结束 ---

    try:
        # 将路径中的 \ 替换为 / 以兼容协议
        path_for_server_norm = str(path_for_server).replace(os.path.sep, '/')
        
        # 发送包含正确路径的 UPLOAD 命令
        response_str, _ = sendAndReceive(sock, f"UPLOAD {path_for_server_norm}", server_address)
        
        if response_str != "UPLOAD_READY":
            print(f"\n[ERROR] Server not ready for upload: {response_str}")
            return

        # 使用解析出的完整本地路径来读取和传输文件
        if transfer_file(sock, server_address, local_path_to_read, is_upload=True):
            response_str, _ = sendAndReceive(sock, "UPLOAD_DONE", server_address)
            if response_str == "UPLOAD_COMPLETE":
                print(f"\n[SUCCESS] File '{path_for_server_norm}' uploaded successfully!")
            else:
                print(f"\n[WARNING] Unexpected final response: {response_str}")
        else:
            print(f"\n[ERROR] Upload failed for '{path_for_server_norm}'")

    except Exception as e:
        print(f"\n[ERROR] Upload failed: {str(e)}")

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

            if transfer_file(sock, server_address, file_path, is_upload=True):
                response_str, _ = sendAndReceive(sock, "UPLOAD_DONE", server_address)
                if response_str != "UPLOAD_COMPLETE":
                    print(f"[WARNING] Unexpected response for '{rel_path}': {response_str}")
            else:
                print(f"[ERROR] Failed to upload '{rel_path}'")

        # Complete the upload
        response_str, _ = sendAndReceive(sock, "SUPLOAD_COMPLETE", server_address)
        if response_str == "SUPLOAD_OK":
            print(f"\n[SUCCESS] Folder '{folder_path.name}' uploaded completely!")
        else:
            print(f"\n[WARNING] Unexpected final response: {response_str}")

    except Exception as e:
        print(f"\n[ERROR] Upload failed: {str(e)}")

# =================================================================
# --- 新增功能 #2: 主同步循环函数 ---
# =================================================================
def start_sync_mode(sock, server_address):
    """
    启动阻塞式的同步循环，使用分块协议上传MD5清单。
    """
    print("\n[SYNC MODE ACTIVATED]")
    print("Client will now sync with the server every 30 seconds.")
    print("Press Ctrl+C to stop syncing and return to the command menu.")
    
    while True:
        try:
            print("\n------------------ New Sync Cycle Started ------------------")
            
            # 1. 生成本地MD5清单
            print(" -> Step 1/5: Generating local MD5 manifest...")
            manifest = generate_md5_manifest("client_files")
            manifest_payload = json.dumps(manifest)
            
            # 2. 将清单分块
            chunk_size = 1024
            chunks = [manifest_payload[i:i+chunk_size] for i in range(0, len(manifest_payload), chunk_size)]
            num_chunks = len(chunks)

            # 3. 与服务器开始分块传输会话
            print(f" -> Step 2/5: Starting sync session for {num_chunks} manifest chunk(s)...")
            response, _ = sendAndReceive(sock, f"SYNC_START {num_chunks}", server_address)
            if response != "SYNC_READY":
                raise Exception(f"Server not ready for sync. Response: {response}")

            # 4. 逐块上传清单
            print(" -> Step 3/5: Uploading manifest chunks...")
            for i, chunk in enumerate(chunks):
                ack_response, _ = sendAndReceive(sock, f"SYNC_CHUNK {i}/{num_chunks}\n{chunk}", server_address)
                if ack_response != f"ACK_CHUNK {i}":
                    raise Exception(f"Manifest chunk {i} upload failed. ACK not received.")

            # 5. 结束清单传输，并获取服务器的"购物清单"
            print(" -> Step 4/5: Finalizing manifest upload...")
            shopping_list_response, _ = sendAndReceive(sock, "SYNC_FINISH", server_address)
            
            # 添加调试信息
            print(f"Debug: Received response from server: {shopping_list_response}")

            # 6. 根据"购物清单"上传文件
            print(" -> Step 5/5: Processing server's file request list...")
            if shopping_list_response.startswith("NEEDS_FILES"):
                try:
                    # 确保正确分割响应
                    parts = shopping_list_response.split('\n', 1)
                    if len(parts) != 2:
                        raise ValueError(f"Invalid response format. Expected 'NEEDS_FILES\\nJSON', got: {shopping_list_response}")
                    
                    json_str = parts[1].strip()
                    print(f"Debug: Attempting to parse JSON: {json_str}")
                    
                    response_data = json.loads(json_str)
                    if not isinstance(response_data, dict) or 'files' not in response_data:
                        raise ValueError(f"Invalid JSON format. Expected dict with 'files' key, got: {response_data}")
                    
                    files_to_upload = response_data['files']
                    if not isinstance(files_to_upload, list):
                        raise ValueError(f"Expected list of files, got: {type(files_to_upload)}")
                    
                    if files_to_upload:
                        print(f" -> Server needs {len(files_to_upload)} file(s). Starting upload...")
                        for file_path in files_to_upload:
                            print(f"    - Uploading '{file_path}'...")
                            handle_upload(sock, server_address, file_path)
                    else:
                        print(" -> All files are in sync.")
                except json.JSONDecodeError as e:
                    print(f"Error parsing server response: {e}")
                    print(f"Raw response: {shopping_list_response}")
                    raise
                except ValueError as e:
                    print(f"Error processing server response: {e}")
                    raise
            else:
                print(" -> All files are in sync.")

            print("\n[+] Sync cycle completed successfully.")
            print("------------------------------------------------------------")
            
            # 7. 倒计时等待下一个周期
            try:
                for i in range(30, 0, -1):
                    print(f'\rNext sync in {i} seconds...  ', end='')
                    time.sleep(1)
                print('\r                           \r', end='') 
            except KeyboardInterrupt:
                raise KeyboardInterrupt

        except KeyboardInterrupt:
            print("\n[SYNC MODE DEACTIVATED] Returning to command menu.")
            break
        except Exception as e:
            print(f"\n[ERROR] An error occurred during sync cycle: {e}")
            print("Waiting 30 seconds before retrying...")
            time.sleep(30)

def download_file(filename, server_host, server_info):
    """Handle file download with simplified logic."""
    file_size, data_port = server_info
    server_data_address = (server_host, data_port)
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    local_file_path = Path("client_files") / Path(filename).name

    try:
        response_str, _ = sendAndReceive(data_sock, f"DOWNLOAD {filename}", server_data_address)
        if response_str != "DOWNLOAD_READY":
            print(f"[ERROR] Server not ready for download: {response_str}")
            return

        if transfer_file(data_sock, server_data_address, local_file_path, is_upload=False):
            print(f"\n[SUCCESS] File '{filename}' downloaded successfully!")
        else:
            print(f"\n[ERROR] Download failed for '{filename}'")

    except Exception as e:
        print(f"[ERROR] Download failed: {str(e)}")
    finally:
        data_sock.close()

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
    """
    Get server address either from command line or user input.
    
    Returns:
        tuple: (server_host, server_port)
    """
    server_host, server_port = parse_command_line_args()
    
    if server_host is None:
        user_input = input("Enter server host (press Enter or type 'local' for localhost): ").strip()
        server_host = 'localhost' if user_input.lower() in ('local', '') else user_input
        print(f"[INFO] Server address set to: {server_host}:{server_port}")
    
    return server_host, server_port

def display_server_files(sock, server_address):
    """
    Display list of files available on the server.
    
    Returns:
        list: List of available files
    """
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
    * <filename>          - Download a file by entering its name
    * cd <folder>         - Change to the specified directory (e.g., cd my_files)
    * cd ..               - Go back to the parent directory
    * all                 - Download all files in the current directory
    * upload <filename>   - Upload a file to the server
    * supload <folder>    - Upload an entire folder to the server
    * sync                - Enter continuous sync mode (client -> server)
    * kill                - kill every files on server
    * (press enter)       - Exit the client

    Enter command: """)

def handle_command(sock, server_address, command, files, server_host):
    """
    Handle user command and execute appropriate action.
    
    Args:
        sock: Socket for communication
        server_address: Server address tuple
        command: User command
        files: List of available files on server
        server_host: Server hostname
    """
    if not command:
        return False
        
    if command.lower().startswith('cd '):
        handle_cd_command(sock, server_address, command)
    elif command.lower().startswith('upload '):
        handle_upload(sock, server_address, command.split(' ', 1)[1])
    elif command.lower().startswith('supload '):
        handle_super_upload(sock, server_address, command.split(' ', 1)[1])
    elif command.lower() == 'sync':
        start_sync_mode(sock, server_address)
    elif command.lower() == 'kill':
        handle_kill_command(sock, server_address)
    elif command.lower() == 'all':
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