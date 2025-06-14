import socket
import os

def main():
    # Create a UDP socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # 直接使用 localhost 和固定端口
    server_host = 'localhost'
    server_port = 51234
    server_address = (server_host, server_port)

    # Get filename from user
    filename = input("Enter the filename to download: ")
    
    # Send DOWNLOAD request to server
    message = f"DOWNLOAD {filename}"
    client_socket.sendto(message.encode('utf-8'), server_address)
    print(f"Sent: {message}")

    # Receive response from server
    response, _ = client_socket.recvfrom(1024)
    response = response.decode('utf-8')
    print(f"Received: {response}")

    # Parse server response
    if response.startswith("OK"):
        # Extract file information from response
        parts = response.split()
        filename = parts[1]
        size = int(parts[3])
        port = int(parts[5])
        print(f"File found: {filename}")
        print(f"Size: {size} bytes")
        print(f"Port: {port}")
    elif response.startswith("ERR"):
        print("Error: File not found on server")

    client_socket.close()

if __name__ == "__main__":
    main()