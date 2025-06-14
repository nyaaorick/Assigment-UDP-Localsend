import socket
import os
import base64
import time


def sendAndReceive(sock, message, server_address, timeout=1.0, max_retries=5):
    """
    :param sock: 用于通信的套接字对象-sock is the socket object for communication
    :param message: 要发送的字符串消息-message is the string message to send
    :param server_address: 目标服务器的 (host, port) 元组- a tuple of (host, port) for the server
    :param timeout: 初始超时时间（秒）- initial timeout in seconds
    :param max_retries: 最大重传次数-maximum number of retries
    :return: 成功时返回 (响应字符串, 服务器地址) 元组-returns a tuple of (response string, server address) on success
    :raises Exception: 所有重传尝试失败后抛出异常-raises an exception if all retries fail
    """
    for attempt in range(max_retries):
        try:
            # 为套接字设置超时时间
            sock.settimeout(timeout)

            # 发送请求
            # print(f"--> [Attempt {attempt + 1}/{max_retries}] Sending to {server_address}: '{message}'")
            sock.sendto(message.encode('utf-8'), server_address)

            # 等待响应
            response_bytes, addr = sock.recvfrom(4096)  # use a larger buffer to accommodate Base64 data
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
    负责完整地传输一个文件

    :param filename: 要下载的文件名
    :param server_host: 服务器的主机名或IP地址-server's hostname or IP address
    :param server_info: 一个包含文件大小和数据端口的元组 (file_size, data_port)
    """
    file_size, data_port = server_info
    server_data_address = (server_host, data_port)
    # 为数据传输创建一个新的UDP套接字
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # print(f"\n[+] Starting download for '{filename}' from {server_data_address}...")

    # 确保本地目录存在
    os.makedirs("client_files", exist_ok=True)
    local_file_path = os.path.join("client_files", filename)

    bytes_received = 0
    chunk_size = 1024 #1kb=1024bytes

    try:
        with open(local_file_path, 'wb') as f:
            # 循环发送FILE GET请求来获取所有数据块-loop to send FILE GET requests to get all data chunks
            while bytes_received < file_size:
                start_byte = bytes_received
                # 修正：结束字节的计算应为闭区间- a correction: the end byte calculation should be a closed interval
                end_byte = min(start_byte + chunk_size - 1, file_size - 1)

                request = f"FILE {filename} GET START {start_byte} END {end_byte}"

                # 使用可靠的函数发送请求并接收数据-i fix the bug of too much parameters, now i only send 3 parameters
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
                    print(f"\rProgress: {progress:.2f}% ({bytes_received}/{file_size} bytes)", end='')
                else:
                    print(f"!!! Error: Unexpected data response: {response_str}")
                    break

        # 结束流程：客户端下载完成后，发送 `FILE <filename> CLOSE` 消息-end the process: after the client downloads the file, send the `FILE <filename> CLOSE` message
        # print(f"[+] File download finished. Sending CLOSE request.")
        close_request = f"FILE {filename} CLOSE"
        response_str, _ = sendAndReceive(data_sock, close_request, server_data_address)

        # 确认服务器的最终响应-confirm the final response from the server
        if f"FILE {filename} CLOSE_OK" in response_str:
            print(f"\n[SUCCESS] Transfer for '{filename}' completed successfully.")
        else:
            print(f"\n[WARNING] Server gave an unexpected response to CLOSE: {response_str}")

    except Exception as e:
        print(f"!!! A critical error occurred during file transfer for '{filename}': {e}")
    finally:
        # 确保数据套接字总是被关闭-guarantee that the data socket is always closed
        data_sock.close()
        # print(f"[-] Data socket for '{filename}' closed.")


def main():
    # 确保客户端文件目录存在-ensure the client files directory exists
    os.makedirs("client_files", exist_ok=True)
    # print("[INFO] Client files directory is ready.")

    # 在循环外部创建唯一的套接字-create the unique socket outside the loop
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    server_host = 'localhost'
    server_port = 51234
    server_address = (server_host, server_port)

    # 开始会话循环-start the session loop
    while True:
        try:
            # 获取服务器上的文件列表-get the file list on server
            files = [] # 初始化文件列表为空-initialize the file list as empty
            try:
                response_str, _ = sendAndReceive(client_sock, "LIST_FILES", server_address)
                if response_str.startswith("OK"):
                    files = response_str.split()[1:] 
                    print("\nAvailable entries on server:")
                    print(" ".join(files) if files else "(empty)")
                    print("-" * 50)
                else:
                    print("Error: Could not get file list from server")
                    continue
            except Exception as e:
                print(f"Error getting file list: {str(e)}")
                continue

            filename = input("""
            *！COMMAND MENU ! ^^^^^check the available entries on server^^^^
            ********************************************
            * <filename>          - Download a file by entering its name
            * cd <folder>         - Change to the specified directory (e.g., cd my_files)
            * cd ..               - Go back to the parent directory
            * all                 - Download all files in the current directory
            * upload <filename>   - Upload a file to the server
            * kill                - kill every files on server
            * (press enter)       - Exit the client

            Enter command: """)
            
            # 如果用户直接按回车，就退出循环
            if not filename:
                break

            # 处理 cd 命令
            if filename.lower().startswith('cd '):
                # 直接将用户的cd命令格式化后发送给服务器
                command_to_send = "CD " + filename.split(' ', 1)[1]
                try:
                    response_str, _ = sendAndReceive(client_sock, command_to_send, server_address)
                    # 打印服务器的响应，例如 "CD_OK Now in /folder" 或 "CD_ERR ..."
                    print(f"Server: {response_str}")
                except Exception as e:
                    print(f"\n[ERROR] Failed to send cd command: {str(e)}")
                # 处理完cd后，循环会重新开始，并自动获取新目录下的列表
                continue

            # 处理上传命令
            if filename.lower().startswith('upload '):
                try:
                    upload_filename = filename[7:].strip()  # 获取文件名
                    local_file_path = os.path.join("client_files", upload_filename)
                    
                    if not os.path.exists(local_file_path):
                        print(f"\n[ERROR] File '{upload_filename}' not found in client_files directory.")
                        print(f"[INFO] Please place the file in the 'client_files' directory and try again.")
                        print(f"[INFO] Current client_files directory: {os.path.abspath('client_files')}")
                        continue

                    # 发送上传请求
                    upload_request = f"UPLOAD {upload_filename}"
                    response_str, _ = sendAndReceive(client_sock, upload_request, server_address)
                    
                    if response_str != "UPLOAD_READY":
                        print(f"\n[ERROR] Server not ready for upload: {response_str}")
                        continue

                    # print(f"\n[INFO] Server ready for upload. Starting file transfer...")
                    # print(f"[INFO] Uploading file: {upload_filename}")
                    # print(f"[INFO] From: {os.path.abspath(local_file_path)}")
                    
                    # 开始文件传输
                    with open(local_file_path, 'rb') as f:
                        file_size = os.path.getsize(local_file_path)
                        bytes_sent = 0
                        chunk_size = 1024  # 1KB chunks

                        while True:
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break

                            # 编码数据块
                            encoded_chunk = base64.b64encode(chunk).decode('utf-8')
                            data_message = f"DATA {encoded_chunk}"
                            
                            # 发送数据块并等待确认
                            response_str, _ = sendAndReceive(client_sock, data_message, server_address)
                            
                            if response_str != "ACK_DATA":
                                print(f"\n[ERROR] Server did not acknowledge data chunk: {response_str}")
                                break

                            bytes_sent += len(chunk)
                            progress = (bytes_sent / file_size) * 100
                            print(f"\rProgress: {progress:.2f}% ({bytes_sent}/{file_size} bytes)", end='')

                    # 发送完成消息
                    response_str, _ = sendAndReceive(client_sock, "UPLOAD_DONE", server_address)
                    
                    if response_str == "UPLOAD_COMPLETE":
                        print(f"\n[SUCCESS] File '{upload_filename}' uploaded successfully!")
                    else:
                        print(f"\n[WARNING] Unexpected final response: {response_str}")

                except Exception as e:
                    print(f"\n[ERROR] Upload failed: {str(e)}")
                continue

            # 处理 'kill' 命令
            if filename.lower() == 'kill':
                try:
                    response_str, _ = sendAndReceive(client_sock, "KILL_SERVER_FILES", server_address)
                    if response_str.startswith("KILL_OK"):
                        print("\n[SUCCESS] All files on server have been deleted successfully.")
                    elif response_str.startswith("KILL_ERR"):
                        print("\n[ERROR] Failed to delete files on server.")
                    else:
                        print(f"\n[WARNING] Unexpected response from server: {response_str}")
                except Exception as e:
                    print(f"\n[ERROR] Failed to send kill command: {str(e)}")
                continue

            # 处理 'all' 命令
            if filename.lower() == 'all':
                if not files:  # 如果文件列表为空
                    print("No files available to download.")
                    continue
                
                # print(f"\nStarting batch download of {len(files)} files...")
                for file_to_download in files:
                    # 跳过目录（以/结尾的项）
                    if file_to_download.endswith('/'):
                        continue
                        
                    # print(f"\n{'='*50}")
                    # print(f"Downloading: {file_to_download}")
                    # print(f"{'='*50}")
                    
                    # 发送 DOWNLOAD 请求
                    message = f"DOWNLOAD {file_to_download}"
                    try:
                        response_str, _ = sendAndReceive(client_sock, message, server_address)
                        # print(f"Received: {response_str}")

                        # 解析服务器响应
                        if response_str.startswith("OK"):
                            parts = response_str.split()
                            returned_filename = parts[1]
                            size = int(parts[3])
                            port = int(parts[5])

                            # print(f"File found: {returned_filename}")
                            # print(f"Size: {size} bytes")
                            # print(f"Port: {port}")

                            server_info = (size, port)
                            download_file(returned_filename, server_host, server_info)

                        elif response_str.startswith("ERR"):
                            print(f"Error: File '{file_to_download}' not found on server")

                    except Exception as e:
                        print(f"Error during download of '{file_to_download}': {str(e)}")
                        continue
                
                print("\nBatch download completed.")
                continue

            # 处理单个文件下载
            message = f"DOWNLOAD {filename}"
            try:
                response_str, _ = sendAndReceive(client_sock, message, server_address)
                # print(f"Received: {response_str}")

                # 解析服务器响应
                if response_str.startswith("OK"):
                    parts = response_str.split()
                    returned_filename = parts[1]
                    size = int(parts[3])
                    port = int(parts[5])

                    # print(f"File found: {returned_filename}")
                    # print(f"Size: {size} bytes")
                    # print(f"Port: {port}")

                    server_info = (size, port)
                    download_file(returned_filename, server_host, server_info)

                elif response_str.startswith("ERR"):
                    print("Error: File not found on server")

            except Exception as e:
                print(f"Error during initial request: {str(e)}")

        except Exception as e:
            print(f"Error: {str(e)}")

    # 在循环结束后，关闭唯一的套接字-close the unique socket after the loop
    print("\nClient session finished. Exiting.")
    client_sock.close()


if __name__ == "__main__":
    import sys
    main()