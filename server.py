import socket
import sys  

def start_server():
    host = 'localhost'  # Server IP address
    port = 9090  # Server port number #never use below 5000

    # Create a TCP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server_socket.bind((host, port))  # Bind the socket to the address and port

    server_socket.listen(5)  # Listen for incoming connections

    print(f"Server listening on {host}:{port}") 
    

    while True:
     client_socket, addr = server_socket.accept()  # Accept a connection from a client
     print(f"Connection from {addr} has been established!")

    #reveive data from client
     message = client_socket.recv(1024).decode()  # Receive data from the client
     print(f"Received message: {message}")

     #send response to client
     response = f"Server received: {message}"
     client_socket.sendall(response.encode('utf-8'))  # Send a response back to the client

     client_socket.close()  # Close the client socket


if __name__ == "__main__":
    start_server()
# #start server

        
