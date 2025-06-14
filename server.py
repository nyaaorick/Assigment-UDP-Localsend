
import socket
import os
import base64


def handle_file_transfer(filename, data_port):
    """
    处理单个文件的完整传输流程（在新端口上）。
    """
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data_sock.bind(('', data_port))
    print(f"[+] Data socket is now listening on port {data_port} for '{filename}'...")

    file_path = os.path.join("serverfile", filename)

    # 2. 进入循环，等待来自客户端的 GET 或 CLOSE 请求
    while True:
        try:
            request_bytes, addr = data_sock.recvfrom(2048)
            request = request_bytes.decode('utf-8')
            print(f"    [Data Port] Received from {addr}: '{request}'")

            # --- 逻辑分离：清晰地处理 GET 和 CLOSE 请求 ---

            # 3. 处理 GET 请求
            if f"FILE {filename} GET" in request:
                parts = request.split()
                start_byte = int(parts[4])
                end_byte = int(parts[6])

                with open(file_path, 'rb') as f:
                    f.seek(start_byte)
                    # 修正了之前存在的BUG：读取的字节数应该是 (end - start + 1)
                    chunk_data = f.read(end_byte - start_byte + 1)
                    encoded_chunk = base64.b64encode(chunk_data).decode('utf-8')

                response = f"FILE {filename} OK START {start_byte} END {end_byte} DATA {encoded_chunk}"
                data_sock.sendto(response.encode('utf-8'), addr)

            # 4. 处理 CLOSE 请求
            elif f"FILE {filename} CLOSE" in request:
                response = f"FILE {filename} CLOSE_OK"
                data_sock.sendto(response.encode('utf-8'), addr)
                print(f"[+] Sent CLOSE_OK. Transfer for '{filename}' is complete.")
                break  # 成功处理CLOSE后，跳出循环，结束此文件的传输

        except Exception as e:
            print(f"!!! An error occurred during file transfer: {e}")
            break  # 发生任何错误也应跳出循环

    # 5. 关闭数据套接字，释放端口
    data_sock.close()
    print(f"[-] Data socket on port {data_port} has been closed.")


def start_server():
    """
    启动主服务器，监听 DOWNLOAD 请求。
    这是一个单线程服务器，一次只能处理一个客户端的完整流程。
    """
    host = ''  # 监听所有接口
    port = 51234

    # 为了简单，我们像你原来一样，使用一个固定的数据端口
    # 在多线程版本中，这里应该是动态分配的
    fixed_data_port = 51235

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind((host, port))
    print(f"[*] Single-threaded server listening on {host or '0.0.0.0'}:{port}")

    while True:
        print("\n======================================================\n"
              "Waiting for a new DOWNLOAD request on the main port...")
        message_bytes, client_addr = server_sock.recvfrom(1024)
        message = message_bytes.decode('utf-8')
        print(f"[Main Port] Received from {client_addr}: '{message}'")

        parts = message.split()
        if len(parts) >= 2 and parts[0] == "DOWNLOAD":
            filename = parts[1]
            file_path = os.path.join("serverfile", filename)

            if os.path.exists(file_path):
                # 文件存在，发送OK响应
                file_size = os.path.getsize(file_path)
                response = f"OK {filename} SIZE {file_size} PORT {fixed_data_port}"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print(f"[Main Port] Sent OK response. Handing off to transfer function...")

                # 开始文件传输处理。
                # 注意：在单线程模型中，程序将在这里被“卡住”，直到文件传输完成。
                handle_file_transfer(filename, fixed_data_port)

            else:
                # 文件不存在，发送ERR响应
                response = f"ERR {filename} NOT_FOUND"
                server_sock.sendto(response.encode('utf-8'), client_addr)
                print(f"[Main Port] Sent ERR NOT_FOUND for '{filename}'.")


if __name__ == "__main__":
    os.makedirs("serverfile", exist_ok=True)
    start_server()