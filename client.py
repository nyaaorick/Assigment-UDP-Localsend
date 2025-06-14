import socket
import os
import base64
import time


def sendAndReceive(sock, message, server_address, timeout=2.0, max_retries=5):
    for attempt in range(max_retries):
        try:
            # 1. 设置超时
            sock.settimeout(timeout)

            # 2. 发送消息
            print(f"--> Sending to {server_address}: '{message}' (Attempt {attempt + 1})")
            sock.sendto(message.encode('utf-8'), server_address)

            # 3. 等待响应
            response_bytes, addr = sock.recvfrom(2048)  # 缓冲区建议比1336稍大
            response_str = response_bytes.decode('utf-8')
            print(f"<-- Received from {addr}: '{response_str}'")

            # 4. 成功接收，返回结果
            return response_str, addr

        except socket.timeout:
            print(f"*** Timeout after {timeout:.1f}s. Retrying... ***")
            # 增加下一次的超时时间
            timeout *= 2
            continue  # 继续下一次尝试

    # 所有尝试都失败后
    raise Exception(f"Server not responding after {max_retries} attempts.")

def download_file(filename, server_host, data_port, file_size):
    # Create a new socket for data transfer
    data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_address = (server_host, data_port)
    
    # Create clientfile directory if it doesn't exist
    os.makedirs("clientfile", exist_ok=True)
    file_path = os.path.join("clientfile", filename)
    
    chunk_size = 1024  # 1KB chunks
    bytes_received = 0
    
    try:
        with open(file_path, 'wb') as f:
            while bytes_received < file_size:
                # Calculate chunk boundaries
                start = bytes_received
                end = min(start + chunk_size, file_size)
                
                # Request chunk
                request = f"FILE {filename} GET START {start} END {end}"
                try:
                    response = sendAndReceive(data_sock, request, server_address)
                    
                    # Parse response
                    parts = response[0].split()
                    if len(parts) >= 8 and parts[0] == "FILE" and parts[2] == "OK":
                        # Extract and decode data
                        data_start = response[0].find("DATA ") + 5
                        encoded_data = response[0][data_start:]
                        chunk_data = base64.b64decode(encoded_data)
                        
                        # Write chunk to file
                        f.write(chunk_data)
                        bytes_received += len(chunk_data)
                        print(f"Received {len(chunk_data)} bytes")
                    else:
                        print(f"Unexpected response: {response[0]}")
                        break
                except Exception as e:
                    print(f"Error receiving chunk: {str(e)}")
                    break
        
        # Send close request with retransmission
        try:
            close_request = f"FILE {filename} CLOSE"
            response = sendAndReceive(data_sock, close_request, server_address)
            if response[0] == f"FILE {filename} CLOSE_OK":
                print("File transfer completed successfully")
            else:
                print("Unexpected response to close request")
        except Exception as e:
            print(f"Error during close: {str(e)}")
            
    except Exception as e:
        print(f"Error during file transfer: {str(e)}")
    finally:
        data_sock.close()

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