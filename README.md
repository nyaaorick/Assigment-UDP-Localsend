# UDP-Localsend

**Author:** JUNYAO SHI  
**ID:** 20233006416  

## Description

All file operations are contained within specific directories: `serverfile` on the server and `client_files` on the client.



## How to Use

1.  Run the client script from your terminal:

    ```bash
    python server.py
    ```

2.  Run the client script from your terminal:

    ```bash
    python client.py
    ```



## Command List

The client accepts the following commands:

| Command           | Description                                                                  |
| :---------------- | :--------------------------------------------------------------------------- |
| `cd <folder>`     | Change to the specified directory on the server (e.g., `cd folder1`).        |
| `cd ..`           | Go back to the parent directory on the server.                               |
| `<filename>`      | Download a specific file by entering its name (e.g., `1.mp4`).               |
| `all`             | Download all files in the current remote directory.                          |
| `upload <filename>` | Upload a file from your local machine to the server's current directory.   |
| `kill`            | **DANGER:** Deletes **every file** on the folder.                            |
| `(press enter)`   | Exit the client application.                                                 |

