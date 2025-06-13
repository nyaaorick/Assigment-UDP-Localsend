import socket

def main():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_address = ('localhost', 9090)  # Server address and port
    client_socket.connect(server_address)  # Connect to the server

    message = input("Enter the message to send: ")  
    client_socket.sendall(message.encode('utf-8'))  # Send the message to the server
    print(f"Sent: {message}")

    client_socket.close()  # Close the socket

if __name__ == "__main__":
    main()