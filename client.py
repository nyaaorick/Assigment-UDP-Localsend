import socket
import os
import base64
import time


def sendAndReceive(sock, message, server_address, timeout=1.0, max_retries=5):
    """
    一个通用的函数，用于发送请求并等待响应，包含超时和重传机制。

    :param sock: 用于通信的套接字对象。
    :param message: 要发送的字符串消息。
    :param server_address: 目标服务器的 (host, port) 元组。
    :param timeout: 初始超时时间（秒）。
    :param max_retries: 最大重传次数。
    :return: 成功时返回 (响应字符串, 服务器地址) 元组。
    :raises Exception: 所有重传尝试失败后抛出异常。
    """
    for attempt in range(max_retries):
        try:
            # 为套接字设置超时时间
            sock.settimeout(timeout)

            # 发送请求
            print(f"--> [Attempt {attempt + 1}/{max_retries}] Sending to {server_address}: '{message}'")
            sock.sendto(message.encode('utf-8'), server_address)

            # 等待响应
            response_bytes, addr = sock.recvfrom(2048)  # 使用稍大的缓冲区以容纳Base64数据
            response_str = response_bytes.decode('utf-8')

            # 成功接收，返回结果
            return response_str, addr

        except socket.timeout:
            # 捕捉超时异常
            print(f"*** Timeout after {timeout:.1f}s. Retrying... ***")
            # 可以在这里增加超时时间，例如 timeout *= 2，以应对网络拥堵
            continue  # 继续下一次尝试

    # 所有尝试都失败后，客户端放弃并报错退出
    raise Exception(f"Server not responding after {max_retries} attempts.")


def download_file(filename, server_host, server_info):
    """
    负责完整地传输一个文件。

    :param filename: 要下载的文件名。
    :param server_host: 服务器的主机名或IP地址。
    :param server_info: 一个包含文件大小和数据端口的元组 (file_size, data_port)。
    """
    file_size, data_port = server_info
    server_data_address = (server_host, data_port)

    # 为数据传输创建一个新的UDP套接字
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"\n[+] Starting download for '{filename}' from {server_data_address}...")

    # 确保本地目录存在
    os.makedirs("client_files", exist_ok=True)
    local_file_path = os.path.join("client_files", filename)

    bytes_received = 0
    # 作业规范中建议的数据块大小为1000字节
    chunk_size = 1000

    try:
        with open(local_file_path, 'wb') as f:
            # 循环发送FILE GET请求来获取所有数据块
            while bytes_received < file_size:
                start_byte = bytes_received
                # 修正：结束字节的计算应为闭区间
                end_byte = min(start_byte + chunk_size - 1, file_size - 1)

                request = f"FILE {filename} GET START {start_byte} END {end_byte}"

                # 使用可靠的函数发送请求并接收数据
                response_str, _ = sendAndReceive(data_sock, request, server_data_address)

                # 解析服务器响应
                data_header = "DATA "
                if f"FILE {filename} OK" in response_str and data_header in response_str:
                    data_start_index = response_str.find(data_header) + len(data_header)
                    encoded_data = response_str[data_start_index:]

                    # 将收到的数据解码并写入本地文件
                    chunk_data = base64.b64decode(encoded_data)
                    f.write(chunk_data)
                    bytes_received += len(chunk_data)

                    progress = (bytes_received / file_size) * 100
                    print(f"    Received chunk. Total: {bytes_received}/{file_size} bytes ({progress:.2f}%)")
                else:
                    print(f"!!! Error: Unexpected data response: {response_str}")
                    break

        # 结束流程：客户端下载完成后，发送 `FILE <filename> CLOSE` 消息
        print(f"[+] File download finished. Sending CLOSE request.")
        close_request = f"FILE {filename} CLOSE"
        response_str, _ = sendAndReceive(data_sock, close_request, server_data_address)

        # 确认服务器的最终响应
        if f"FILE {filename} CLOSE_OK" in response_str:
            print(f"[SUCCESS] Transfer for '{filename}' completed successfully.")
        else:
            print(f"[WARNING] Server gave an unexpected response to CLOSE: {response_str}")

    except Exception as e:
        print(f"!!! A critical error occurred during file transfer for '{filename}': {e}")
    finally:
        # 确保数据套接字总是被关闭
        data_sock.close()
        print(f"[-] Data socket for '{filename}' closed.")







def main():
    # Create a UDP socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # 直接使用 localhost 和固定端口
    server_host = 'localhost'
    server_port = 51234
    server_address = (server_host, server_port)

    try:
        # Get filename from user
        filename = input("Enter the filename to download: ")
        
        # Send DOWNLOAD request with retransmission
        message = f"DOWNLOAD {filename}"
        try:
            response = sendAndReceive(client_socket, message, server_address)
            print(f"Received: {response[0]}")

            # Parse server response
            if response[0].startswith("OK"):
                # Extract file information from response
                parts = response[0].split()
                filename = parts[1]
                size = int(parts[3])
                port = int(parts[5])
                print(f"File found: {filename}")
                print(f"Size: {size} bytes")
                print(f"Port: {port}")
                
                # Start file download
                download_file(filename, server_host, port, size)
            elif response[0].startswith("ERR"):
                print("Error: File not found on server")
        except Exception as e:
            print(f"Error during initial request: {str(e)}")

    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client_socket.close()

if __name__ == "__main__":
    main()