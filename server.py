import socket
import os

def start_server():
    # 直接使用 localhost 和固定端口
    host = 'localhost'
    port = 51234
    data_port = 51235  # Port for data transfer (hardcoded for now)

    # Create a UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Bind the socket to the address and port
    server_socket.bind((host, port))

    print(f"Server listening on {host}:{port}")

    while True:
        # Receive data from client
        data, addr = server_socket.recvfrom(1024)
        message = data.decode()
        print(f"Received message from {addr}: {message}")

        # Parse the message
        parts = message.split()
        if len(parts) >= 2 and parts[0] == "DOWNLOAD":
            filename = parts[1]
            file_path = os.path.join("serverfile", filename)
            
            if os.path.exists(file_path):
                # File exists, send OK response with file info
                file_size = os.path.getsize(file_path)
                response = f"OK {filename} SIZE {file_size} PORT {data_port}"
            else:
                # File doesn't exist, send error response
                response = f"ERR {filename} NOT_FOUND"
            
            server_socket.sendto(response.encode('utf-8'), addr)
            print(f"Sent response: {response}")

if __name__ == "__main__":
    start_server()

        
