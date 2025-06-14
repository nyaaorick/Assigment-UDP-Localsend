import socket
import os
import base64
import threading
import shutil  # Added for recursive directory deletion

### MODIFICATION START: 1. 定义服务器的根目录 ###
# 将根目录定义为一个全局常量，方便引用
SERVER_BASE_DIR = os.path.realpath("serverfile")
### MODIFICATION END ###

def handle_file_transfer(filename, data_port, client_path):
    """
    处理单个文件的完整传输流程（在新端口上）
    """
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data_sock.bind(('', data_port))
    print(f"[+] Data socket is now listening on port {data_port} for '{filename}'...")

    ### MODIFICATION START: 3. 使用传入的 client_path 拼接路径 ###
    # 原代码: file_path = os.path.join("serverfile", filename)
    # 不再使用硬编码的 "serverfile"，而是使用客户端当前的虚拟路径
    file_path = os.path.join(client_path, filename)
    ### MODIFICATION END ###

    while True:
        try:
            request_bytes, addr = data_sock.recvfrom(2048)
            request = request_bytes.decode('utf-8')
            print(f"    [Data Port] Received from {addr}: '{request}'")

            if f"FILE {filename} GET" in request:
                parts = request.split()
                start_byte = int(parts[4])
                end_byte = int(parts[6])

                # 检查文件是否存在于这个路径下，这是一个好的安全习惯
                if not os.path.isfile(file_path):
                    # 文件可能在线程启动后被删除或移动
                    print(f"!!! File not found at path: {file_path}")
                    break

                with open(file_path, 'rb') as f:
                    f.seek(start_byte)
                    chunk_data = f.read(end_byte - start_byte + 1)
                    encoded_chunk = base64.b64encode(chunk_data).decode('utf-8')

                response = f"FILE {filename} OK START {start_byte} END {end_byte} DATA {encoded_chunk}"
                data_sock.sendto(response.encode('utf-8'), addr)

            elif f"FILE {filename} CLOSE" in request:
                response = f"FILE {filename} CLOSE_OK"
                data_sock.sendto(response.encode('utf-8'), addr)
                print(f"[+] Sent CLOSE_OK. Transfer for '{filename}' is complete.")
                break

        except Exception as e:
            print(f"!!! An error occurred during file transfer: {e}")
            break

    data_sock.close()
    print(f"[-] Data socket on port {data_port} has been closed.")

def receive_file_data(sock, original_client_addr, target_file_path):
    """
    一个无状态的辅助函数，在主套接字上接收一个完整的文件数据。
    它被 UPLOAD 和 SUPLOAD_FILE 独立调用。
    """
    print(f"    [Util] Receiving data for -> {os.path.abspath(target_file_path)}")
    try:
        # 确保目标目录存在
        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)
        with open(target_file_path, 'wb') as f:
            while True:
                # 注意：使用原始的 client_addr 回复，避免多用户干扰
                data_bytes, recv_addr = sock.recvfrom(4096)
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

def start_server():
    """
    启动主服务器，监听请求。
    """
    os.makedirs(SERVER_BASE_DIR, exist_ok=True)
    print(f"[INFO] Server files directory is ready at: {SERVER_BASE_DIR}")

    host = ''
    port = 51234
    base_data_port = 51235
    
    # 为两个独立的功能分别设置状态字典
    client_paths = {}      # 用于标准文件操作 (cd, upload, list)
    supload_sessions = {}  # 仅用于 supload 文件夹上传

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind((host, port))
    print(f"[*] Final independent-module server listening on {host or '0.0.0.0'}:{port}")

    while True:
        try:
            print("\n======================================================")
            message_bytes, client_addr = server_sock.recvfrom(8192)

            message_str = message_bytes.decode('utf-8')
            parts = message_str.split('\n', 1)
            command_line = parts[0]
            payload = parts[1] if len(parts) > 1 else ""
            
            print(f"[Main Port] Request from {client_addr}: '{command_line}'")
            current_client_path = client_paths.get(client_addr, SERVER_BASE_DIR)

            # --- 系统一：标准文件与目录操作 (依赖 client_paths) ---
            if command_line.startswith("CD "):
                target_dir = command_line.split(" ", 1)[1]
                new_path = ""
                if target_dir == "..":
                    new_path = os.path.dirname(current_client_path) if current_client_path != SERVER_BASE_DIR else SERVER_BASE_DIR
                else:
                    new_path = os.path.join(current_client_path, target_dir)
                
                real_new_path = os.path.realpath(new_path)
                if os.path.isdir(real_new_path) and real_new_path.startswith(SERVER_BASE_DIR):
                    client_paths[client_addr] = real_new_path
                    response = f"CD_OK Now in /{os.path.relpath(real_new_path, SERVER_BASE_DIR) or '.'}"
                else:
                    response = "CD_ERR Directory not found or invalid."
                server_sock.sendto(response.encode('utf-8'), client_addr)

            elif command_line == "LIST_FILES":
                entries = os.listdir(current_client_path)
                files = [f for f in entries if os.path.isfile(os.path.join(current_client_path, f))]
                dirs = [f"{d}/" for d in entries if os.path.isdir(os.path.join(current_client_path, d))]
                response = "OK " + " ".join(dirs + files)
                server_sock.sendto(response.encode('utf-8'), client_addr)

            elif command_line.startswith("UPLOAD "):
                filename = command_line.split(' ', 1)[1]
                file_path = os.path.join(current_client_path, filename)
                server_sock.sendto(b"UPLOAD_READY", client_addr)
                # 调用通用工具函数
                receive_file_data(server_sock, client_addr, file_path)

            elif command_line.startswith("DOWNLOAD "):
                filename = command_line.split(' ', 1)[1]
                file_path = os.path.join(current_client_path, filename)
                if os.path.isfile(file_path):
                    data_port = base_data_port + threading.active_count()
                    response = f"OK {filename} SIZE {os.path.getsize(file_path)} PORT {data_port}"
                    server_sock.sendto(response.encode('utf-8'), client_addr)
                    threading.Thread(target=handle_file_transfer, args=(filename, data_port, current_client_path)).start()
                else:
                    server_sock.sendto(f"ERR {filename} NOT_FOUND".encode('utf-8'), client_addr)
            
            # --- 系统二：独立的文件夹上传操作 (依赖 supload_sessions) ---
            elif command_line.startswith("SUPLOAD_STRUCTURE "):
                root_folder_name = command_line.split(' ', 1)[1]
                base_path = os.path.join(current_client_path, root_folder_name)
                os.makedirs(base_path, exist_ok=True)
                supload_sessions[client_addr] = {'base_path': base_path}
                print(f"  [SUPLOAD] Session started. Base path: '{base_path}'")
                for rel_dir in payload.split('\n'):
                    if rel_dir:
                        os.makedirs(os.path.join(base_path, rel_dir.replace('/', os.path.sep)), exist_ok=True)
                server_sock.sendto(b"STRUCTURE_OK", client_addr)

            elif command_line.startswith("SUPLOAD_FILE "):
                session = supload_sessions.get(client_addr)
                if session:
                    relative_file_path = command_line.split(' ', 1)[1]
                    full_save_path = os.path.join(session['base_path'], relative_file_path.replace('/', os.path.sep))
                    server_sock.sendto(b"FILE_READY", client_addr)
                    # 调用同一个通用工具函数
                    receive_file_data(server_sock, client_addr, full_save_path)
                else:
                    server_sock.sendto(b"ERR_NO_SUPLOAD_SESSION", client_addr)
            
            elif command_line == "SUPLOAD_COMPLETE":
                if client_addr in supload_sessions:
                    supload_sessions.pop(client_addr)
                    print(f"  [SUPLOAD] Session for {client_addr} cleared.")
                server_sock.sendto(b"SUPLOAD_OK", client_addr)
            
            # --- 其他指令 ---
            elif command_line == "KILL_SERVER_FILES":
                shutil.rmtree(SERVER_BASE_DIR)
                os.makedirs(SERVER_BASE_DIR)
                server_sock.sendto(b"KILL_OK All files and directories deleted successfully.", client_addr)

            else:
                server_sock.sendto(b"ERR_UNKNOWN_COMMAND", client_addr)
        
        except Exception as e:
            print(f"\n!!! [FATAL] An error occurred in the main loop: {e}")


if __name__ == "__main__":
    start_server()