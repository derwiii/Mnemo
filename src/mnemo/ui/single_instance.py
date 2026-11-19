"""Per-data-directory process lock and event-driven local activation channel."""

import hashlib
import os
from pathlib import Path

from PyQt6.QtCore import QObject, QLockFile, QThread, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = pyqtSignal()

    def __init__(self, directory: Path):
        super().__init__()
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.name = 'mnemo-' + hashlib.sha256(str(directory).casefold().encode()).hexdigest()[:24]
        self.lock = QLockFile(str(directory / '.mnemo.lock'))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._receive)

    def start(self) -> bool:
        if not self.lock.tryLock(0):
            # Allow a first process to finish initializing its activation endpoint.
            for _ in range(20):
                socket = QLocalSocket()
                socket.connectToServer(self.name)
                if socket.waitForConnected(100):
                    if os.name == 'nt':
                        import ctypes
                        ctypes.windll.user32.AllowSetForegroundWindow(-1)
                    socket.write(b'activate')
                    socket.flush()
                    if socket.bytesToWrite():
                        socket.waitForBytesWritten(500)
                    if socket.bytesAvailable() or socket.waitForReadyRead(2500):
                        if bytes(socket.readAll()) == b'ok':
                            socket.disconnectFromServer()
                            return False
                    raise OSError("Запрос отправлен, но работающее Mnemo пока не подтвердило открытие окна.")
                QThread.msleep(100)
            raise OSError("Mnemo уже запущено, но его окно пока не удалось открыть. Попробуйте значок в трее.")
        QLocalServer.removeServer(self.name)  # Only the lock owner can remove stale endpoints.
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise OSError("Не удалось создать локальный канал открытия Mnemo")
        return True

    def _receive(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket):
        if socket.readAll():
            self.activated.emit()
            socket.write(b'ok')
            socket.flush()
        socket.disconnectFromServer()

    def close(self):
        if self.lock.isLocked():
            self.server.close()
            QLocalServer.removeServer(self.name)
            self.lock.unlock()
