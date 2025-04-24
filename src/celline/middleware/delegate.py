import os
import paramiko


def sync_execute(server_ip, username, password, remote_path, local_path="src"):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(server_ip, username=username, password=password)

    sftp = ssh.open_sftp()

    # ローカルディレクトリを再帰的に転送
    for root, dirs, files in os.walk(local_path):
        for filename in files:
            local_filepath = os.path.join(root, filename)
            remote_filepath = os.path.join(remote_path, local_filepath)

            # 必要に応じてリモートのディレクトリを作成
            try:
                sftp.mkdir(os.path.dirname(remote_filepath))
            except IOError:
                pass  # ディレクトリが既に存在する場合

            # ファイルを転送
            sftp.put(local_filepath, remote_filepath)

    sftp.close()

    # Shell.execute関数をリモートで実行
    stdin, stdout, stderr = ssh.exec_command("Shell.execute")

    # 実行結果を取得
    for line in stdout:
        print(line.strip("\n"))

    ssh.close()


# 使用例
sync_execute("192.168.1.1", "username", "password", "/path/on/server")
