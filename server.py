import socket
import os
import base64
import threading

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


def start_server():
    """
    启动主服务器，监听请求。
    """
    os.makedirs(SERVER_BASE_DIR, exist_ok=True)
    print(f"[INFO] Server files directory is ready at: {SERVER_BASE_DIR}")

    host = ''
    port = 51234
    base_data_port = 51235

    ### MODIFICATION START: 4. 增加一个字典来追踪每个客户端的路径 ###
    client_paths = {}
    ### MODIFICATION END ###

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind((host, port))
    print(f"[*] Multi-threaded server listening on {host or '0.0.0.0'}:{port}")

    while True:
        print("\n======================================================\n"
              "Waiting for a new request on the main port...")
        message_bytes, client_addr = server_sock.recvfrom(1024)
        message = message_bytes.decode('utf-8')
        print(f"[Main Port] Received from {client_addr}: '{message}'")
        
        ### MODIFICATION START: 5. 获取当前客户端的路径，如果不存在则使用根目录 ###
        current_client_path = client_paths.get(client_addr, SERVER_BASE_DIR)
        ### MODIFICATION END ###

        ### NEW FUNCTION: 6. 增加处理 CD 命令的逻辑 ###
        if message.startswith("CD "):
            target_dir = message.split(" ", 1)[1]
            new_path = ""
            
            if target_dir == "..":
                # 返回上一级，但不能越过根目录
                if current_client_path != SERVER_BASE_DIR:
                    new_path = os.path.dirname(current_client_path)
                else:
                    new_path = SERVER_BASE_DIR
            else:
                # 进入子目录
                new_path = os.path.join(current_client_path, target_dir)

            # 安全性检查：确保新路径是存在的目录，并且在根目录之下
            real_new_path = os.path.realpath(new_path)
            if os.path.isdir(real_new_path) and real_new_path.startswith(SERVER_BASE_DIR):
                client_paths[client_addr] = real_new_path
                relative_path = os.path.relpath(real_new_path, SERVER_BASE_DIR) or "."
                response = f"CD_OK Now in /{relative_path}"
            else:
                response = "CD_ERR Directory not found or invalid."
            
            server_sock.sendto(response.encode('utf-8'), client_addr)
            continue
        ### NEW FUNCTION END ###

        elif message == "LIST_FILES":
            ### MODIFICATION START: 7. 修改 LIST_FILES 以使用当前路径 ###
            # 筛选出文件和文件夹
            entries = os.listdir(current_client_path)
            files = [f for f in entries if os.path.isfile(os.path.join(current_client_path, f))]
            dirs = [f"{d}/" for d in entries if os.path.isdir(os.path.join(current_client_path, d))]
            
            # 将文件夹放在前面，并合并列表
            sorted_list = dirs + files
            response = "OK " + " ".join(sorted_list)
            ### MODIFICATION END ###
            server_sock.sendto(response.encode('utf-8'), client_addr)
            print(f"[Main Port] Sent file list from '{current_client_path}'")
            continue

        elif message == "KILL_SERVER_FILES":
            ### MODIFICATION START: 8. 修改 KILL_SERVER_FILES 以使用当前路径 ###
            files = [f for f in os.listdir(current_client_path) if os.path.isfile(os.path.join(current_client_path, f))]
            if not files:
                response = "KILL_OK Files deleted successfully. (No files to delete)"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print("[Main Port] No files to delete.")
                continue

            for filename in files:
                file_path = os.path.join(current_client_path, filename)
                try:
                    os.remove(file_path)
                    print(f"[Main Port] Deleted file: {filename}")
                except Exception as e:
                    print(f"[Main Port] Error deleting {filename}: {e}")
                    response = "KILL_ERR Deletion failed."
                    server_sock.sendto(response.encode('utf-8'), client_addr)
                    continue

            response = "KILL_OK Files deleted successfully."
            server_sock.sendto(response.encode('utf-8'), client_addr)
            print("[Main Port] All files deleted successfully.")
            ### MODIFICATION END ###
            continue

        elif message.startswith("UPLOAD "):
            try:
                ### MODIFICATION START: 9. 修改 UPLOAD 以使用当前路径 ###
                filename = message[7:].strip()
                file_path = os.path.join(current_client_path, filename)
                ### MODIFICATION END ###
                
                # 发送准备就绪消息
                response = "UPLOAD_READY"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print(f"[Main Port] Ready to receive file: {filename}")
                print(f"[Main Port] Will save to: {os.path.abspath(file_path)}")

                # 创建或清空目标文件
                with open(file_path, 'wb') as f:
                    while True:
                        # 等待数据块
                        data_bytes, client_addr = server_sock.recvfrom(4096)  # 使用更大的缓冲区
                        data_message = data_bytes.decode('utf-8')

                        if data_message == "UPLOAD_DONE":
                            response = "UPLOAD_COMPLETE"
                            server_sock.sendto(response.encode('utf-8'), client_addr)
                            print(f"[Main Port] File upload completed: {filename}")
                            print(f"[Main Port] File saved at: {os.path.abspath(file_path)}")
                            break

                        if data_message.startswith("DATA "):
                            try:
                                # 解码数据块
                                encoded_data = data_message[5:]
                                chunk_data = base64.b64decode(encoded_data)
                                
                                # 写入文件
                                f.write(chunk_data)
                                
                                # 发送确认
                                response = "ACK_DATA"
                                server_sock.sendto(response.encode('utf-8'), client_addr)
                                
                            except Exception as e:
                                print(f"[Main Port] Error processing data chunk: {e}")
                                break

            except Exception as e:
                print(f"[Main Port] Error during file upload: {e}")
            continue
        
        parts = message.split()
        if len(parts) >= 2 and parts[0] == "DOWNLOAD":
            filename = parts[1]
            ### MODIFICATION START: 10. 修改 DOWNLOAD 以使用当前路径 ###
            file_path = os.path.join(current_client_path, filename)

            # 检查现在是文件，而不是文件夹
            if os.path.isfile(file_path):
                data_port = base_data_port + threading.active_count()
                file_size = os.path.getsize(file_path)
                response = f"OK {filename} SIZE {file_size} PORT {data_port}"
                server_sock.sendto(response.encode('utf-8'), client_addr)

                # 创建新线程时，必须把当前路径传递给它
                transfer_thread = threading.Thread(
                    target=handle_file_transfer,
                    args=(filename, data_port, current_client_path) # 传入路径
                )
                transfer_thread.daemon = True
                transfer_thread.start()
            else:
                response = f"ERR {filename} NOT_FOUND_OR_IS_A_DIRECTORY"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print(f"[Main Port] Sent ERR for '{filename}' because it's not a file.")
            ### MODIFICATION END ###


if __name__ == "__main__":
    start_server()