import socket

def main():
    # Create a UDP socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # 直接使用 localhost 和固定端口
    server_host = 'localhost'
    server_port = 51234
    server_address = (server_host, server_port)

    # Send message to server
    message = "Hello, Server"
    client_socket.sendto(message.encode('utf-8'), server_address)
    print(f"Sent: {message}")

    client_socket.close()

if __name__ == "__main__":
    main()