import socket
import os
import base64
import threading


def handle_file_transfer(filename, data_port):
    """
    处理单个文件的完整传输流程（在新端口上）-handle the complete transfer process of a single file (on a new port)
    """
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data_sock.bind(('', data_port))
    print(f"[+] Data socket is now listening on port {data_port} for '{filename}'...")

    file_path = os.path.join("serverfile", filename)

    while True:
        try:
            request_bytes, addr = data_sock.recvfrom(2048)
            request = request_bytes.decode('utf-8')
            print(f"    [Data Port] Received from {addr}: '{request}'")

            if f"FILE {filename} GET" in request:
                parts = request.split()
                start_byte = int(parts[4])
                end_byte = int(parts[6])

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
    启动主服务器，监听 DOWNLOAD 请求。
    这是一个多线程服务器，可以同时处理多个客户端的请求。
    this is a multi-threaded server, it can handle multiple client requests at the same time.
    """
    # 确保服务器文件目录存在
    os.makedirs("serverfile", exist_ok=True)
    print(f"[INFO] Server files directory is ready at: {os.path.abspath('serverfile')}")

    host = ''
    port = 51234
    base_data_port = 51235

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind((host, port))
    print(f"[*] Multi-threaded server listening on {host or '0.0.0.0'}:{port}")

    while True:
        print("\n======================================================\n"
              "Waiting for a new request on the main port...")
        message_bytes, client_addr = server_sock.recvfrom(1024)
        message = message_bytes.decode('utf-8')
        print(f"[Main Port] Received from {client_addr}: '{message}'")

        if message == "LIST_FILES":
            # 获取serverfile目录中的所有文件
            files = os.listdir("serverfile")
            response = "OK " + " ".join(files)
            server_sock.sendto(response.encode('utf-8'), client_addr)
            print(f"[Main Port] Sent file list: {files}")
            continue

        elif message == "KILL_SERVER_FILES":
            try:
                # 获取所有文件列表
                files = os.listdir("serverfile")
                if not files:
                    response = "KILL_OK Files deleted successfully. (No files to delete)"
                    server_sock.sendto(response.encode('utf-8'), client_addr)
                    print("[Main Port] No files to delete.")
                    continue

                # 删除所有文件
                for filename in files:
                    file_path = os.path.join("serverfile", filename)
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
            except Exception as e:
                print(f"[Main Port] Error during file deletion: {e}")
                response = "KILL_ERR Deletion failed."
                server_sock.sendto(response.encode('utf-8'), client_addr)
            continue

        elif message.startswith("UPLOAD "):
            try:
                # 解析文件名
                filename = message[7:].strip()
                file_path = os.path.join("serverfile", filename)
                
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
            file_path = os.path.join("serverfile", filename)

            if os.path.exists(file_path):
                # 为每个客户端分配一个唯一的数据端口
                data_port = base_data_port + threading.active_count()
                file_size = os.path.getsize(file_path)
                response = f"OK {filename} SIZE {file_size} PORT {data_port}"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print(f"[Main Port] Sent OK response. Starting transfer thread...")

                # 创建新线程处理文件传输
                transfer_thread = threading.Thread(
                    target=handle_file_transfer,
                    args=(filename, data_port)
                )
                transfer_thread.daemon = True
                transfer_thread.start()

            else:
                response = f"ERR {filename} NOT_FOUND"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print(f"[Main Port] Sent ERR NOT_FOUND for '{filename}'.")


if __name__ == "__main__":
    start_server()