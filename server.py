import socket

def start_server():
    # 直接使用 localhost 和固定端口
    host = 'localhost'
    port = 51234

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

if __name__ == "__main__":
    start_server()

        
