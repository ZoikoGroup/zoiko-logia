"""Test-only real HTTP worker. No identity/DB overrides; no external transports."""
import os
import socket
import groq

_original_connect = socket.socket.connect

def _local_only(sock, address):
    if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
        raise RuntimeError('External transport forbidden in socket integration test')
    if isinstance(address, str) and not address.startswith('/private/tmp/kriton-visual-'):
        raise RuntimeError('Non-test Unix socket forbidden')
    return _original_connect(sock, address)

socket.socket.connect = _local_only
async def _no_provider(*args, **kwargs):
    raise RuntimeError('Live model transport forbidden in socket integration test')
groq.AsyncGroq.request = _no_provider
from app.main import create_app
app = create_app()

@app.get('/__isolated_ready')
def ready():
    return {'isolated':True}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['SOCKET_TEST_PORT']), lifespan='off', log_level='warning')
