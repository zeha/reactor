import socket
import select


_DEBUG = False

class Connection(object):

    def __init__(self, socket, address):
        self.socket = socket
        self.address = address
        self.receive_buffer = b''
        self.transmit_buffer = b''


    def receive(self, context):
        data = self.socket.recv(1024)
        if not data:
            self.shutdown(context)
            return
        self.receive_buffer += data
        self.receive_buffer_full(context)


    def receive_buffer_full(self, context):
        pass


    def consume_receive_buffer(self, length):
        self.receive_buffer = self.receive_buffer[length:]


    def transmit(self, context):
        byteswritten = self.socket.send(self.transmit_buffer)
        self.transmit_buffer = self.transmit_buffer[byteswritten:]
        if len(self.transmit_buffer) == 0:
            self.transmit_buffer_empty(context)


    def transmit_buffer_empty(self, context):
        context.set_file_done(self.fileno())
        self.shutdown(context)


    def shutdown(self, context):
        if _DEBUG: print('Shutdown %r' % self.socket)
        context.set_file_done(self.fileno())
        self.socket.shutdown(socket.SHUT_RDWR)


    def fileno(self):
        return self.socket.fileno()


    def close(self):
        if _DEBUG: print('Close %r' % self.socket)
        self.socket.close()



class GenericSocket(object):

    def fileno(self):
        return self.socket.fileno()


    def close(self):
        self.socket.close()



class ServerSocket(GenericSocket):

    def __init__(self):
        self.listen()

    # downstream classes must implement listen, calling create_listen_socket,
    # and accept, returning a Connection obj.

    def fileno(self):
        return self.socket.fileno()


    def close(self):
        self.socket.close()


    def create_listen_socket(self, listen_addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.bind(listen_addr)
        sock.listen(100)
        sock.setblocking(0)
        self.socket = sock



class ClientConnection(Connection):

    def __init__(self, address):
        sock = socket.create_connection(address)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        super().__init__(sock, address)


    def transmit_buffer_empty(self, context):
        context.set_file_in(self.fileno())


class Reactor:

    def __init__(self, server_sockets=None):
        self.connections = {}
        self.server_sockets = server_sockets or []
        self.epoll = select.epoll()
        self.server_filenos = [sock.fileno() for sock in self.server_sockets]
        for sock in self.server_sockets:
            self.epoll.register(sock.fileno(), select.EPOLLIN)


    def add_client(self, connection):
        self.epoll.register(connection.fileno(), select.EPOLLOUT)
        self.connections[connection.fileno()] = connection


    def accept(self, fileno):
        serversocket = self.server_sockets[self.server_filenos.index(fileno)]
        connection = serversocket.accept()
        connection.socket.setblocking(0)
        self.epoll.register(connection.fileno(), select.EPOLLIN)
        self.connections[connection.fileno()] = connection


    def run(self):
        while self.dispatch():
            pass


    def dispatch(self, timeout=1.0):
        events = self.epoll.poll(timeout=timeout)
        for fileno, event in events:
            if fileno in self.server_filenos:
                self.accept(fileno)
            elif event & select.EPOLLIN:
                if _DEBUG: print('receive')
                self.connections[fileno].receive(self)
            elif event & select.EPOLLOUT:
                if _DEBUG: print('transmit')
                self.connections[fileno].transmit(self)
            elif event & select.EPOLLHUP:
                if _DEBUG: print('Connection closed')
                self.epoll.unregister(fileno)
                self.connections[fileno].close()
                del self.connections[fileno]
            else:
                print(event)
        else:
            if _DEBUG: print('Timer expired')
        if len(self.server_sockets) == 0 and len(self.connections) == 0:
            return False
        return True

    def set_file_in(self, fileno):
        self.epoll.modify(fileno, select.EPOLLIN)


    def set_file_out(self, fileno):
        self.epoll.modify(fileno, select.EPOLLOUT)


    def set_file_done(self, fileno):
        self.epoll.modify(fileno, 0)


    def stop(self):
        for sock in self.server_sockets:
            self.epoll.unregister(sock.fileno())
        self.epoll.close()
        for sock in self.server_sockets:
            sock.close()
