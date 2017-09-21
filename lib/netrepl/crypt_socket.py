# Network access layer for netrepl
#
# Author ulno (http://ulno.net)
# Created: 2017-09-20

import time
import errno
from chacha import ChaCha

_upy=False

try: # micropython
    from micropython import const
    from time import ticks_ms, ticks_diff,sleep_ms
    _upy=True
except: # normal python
    def const(a): return a
    def ticks_ms(): return int(time.clock() * 1000)
    def ticks_diff(a, b): return a - b
    def sleep_ms(t): time.sleep(t/1000)

NETBUF_SIZE = const(192)

class Crypt_Socket:

    # micropython
    def _sock_write(self,a):
        return self.socket.write(a)

    def _sock_readinto(self,a):
        return self.socket.readinto(a)

    # normal python
    def _sock_send(self,a):
        return self.socket.send(a)

    def _sock_read(self,a):
        b=self.socket.recv(1)
        if len(b) == 0:
            return None
        else:
            a[0]=b[0]
            return 1

    def __init__(self, socket):
        global _upy
        # need in and out buffers as reading and writing can happen concurrently
        self.netbuf_in = bytearray(NETBUF_SIZE)
        self.netbuf_in_mv = memoryview(self.netbuf_in)
        self.netbuf_out = bytearray(NETBUF_SIZE)
        self.netbuf_out_mv = memoryview(self.netbuf_out)
        self.crypt_in = None
        self.crypt_out = None
        self.socket = socket
        if _upy:
            self.sock_write = self._sock_write
            self.sock_read = self._sock_readinto
        else:
            self.sock_write = self._sock_send
            self.sock_read = self._sock_read
        socket.setblocking(False) # non blocking

    def init_in(self, key, iv):
        self.crypt_in = ChaCha(key,iv)

    def init_out(self, key, iv):
        self.crypt_out = ChaCha(key,iv)

    def send(self, datain, length=None):
        #print("Sending",datain)
        if length is None: l=len(datain)
        else: l=length
        if l>NETBUF_SIZE:
            raise Exception("Can't send packages longer than {} bytes.".format(NETBUF_SIZE))
        self.netbuf_out[0:l] = datain[0:l]
        self.crypt_out.encrypt(self.netbuf_out, length=l)
        self._write(l) # as padded, send full block

    def _write(self, length):
        # we need to write all the data but it's a non-blocking socket
        # so loop until it's all written eating EAGAIN exceptions
        data=self.netbuf_out_mv
        written=0
        while written < length:
            try:
                written += self.sock_write(data[written:length])
            except OSError as e:
                if len(e.args) > 0 and e.args[0] == errno.EAGAIN:
                    # can't write yet, try again
                    pass
                else:
                    # something else...propagate the exception
                    raise


    def receive(self, request=0, timeoutms=None):
        # receive into network buffer,
        # fill buffer once and decrypt
        # if request>0 wait blocking for request number of bytes (if timeout
        # given interrupt after timeoutms ms)
        data = self.netbuf_in
        data_mv = self.netbuf_in_mv
        readbytes = 0
        start_t = ticks_ms()
        while readbytes < NETBUF_SIZE:
            try:
                if self.sock_read(data_mv[readbytes:readbytes+1]):
                    readbytes += 1
                else:
                    if readbytes >= request:
                        break  # break if not blocking to request size
            except OSError as e:
                if len(e.args) > 0 \
                        and (e.args[0] == errno.EAGAIN
                        or e.args[0] == errno.ETIMEDOUT):
                    if readbytes >= request:
                        break  # break if not blocking to request size
                else:
                    raise
            if timeoutms is not None \
                    and ticks_diff(ticks_ms(), start_t) >= timeoutms:
                break
            sleep_ms(1) # prevent busy waiting
        if readbytes>0: self.crypt_in.decrypt(data,length=readbytes)
        return data,readbytes

    def close(self):
        self.socket.close()