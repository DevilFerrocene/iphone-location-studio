import asyncio
import contextlib
import json
import secrets
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from trajectory import generate

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
PORT = 8769


class Controller:
    def __init__(self):
        self.worker = None
        self.lock = asyncio.Lock()
        self.task = None
        self.route = None
        self.gate = asyncio.Event()
        self.gate.set()
        self.status = {'connected': False, 'mode': 'idle', 'sent': 0, 'total': 0, 'position': None, 'error': '', 'elapsed': 0}

    async def close_worker(self):
        if self.worker:
            if self.worker.returncode is None:
                self.worker.terminate()
                try:
                    await asyncio.wait_for(self.worker.wait(), 3)
                except asyncio.TimeoutError:
                    self.worker.kill()
                    await self.worker.wait()
            self.worker = None
        self.status['connected'] = False

    async def response(self):
        while True:
            line = await asyncio.wait_for(self.worker.stdout.readline(), 25)
            if not line:
                raise RuntimeError('设备连接已关闭，请解锁手机并重新连接')
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if 'error' in data:
                raise RuntimeError(data['error'])
            return data

    async def connect(self):
        async with self.lock:
            if self.worker and self.worker.returncode is None and self.status['connected']:
                return
            await self.close_worker()
            # 只允许一个已配对的 USB 设备，避免把轨迹发送到其他设备。
            proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'list', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), 15)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError('设备识别超时，请重新连接数据线')
            devices = [d for d in json.loads(out) if d.get('ConnectionType') == 'USB' and d.get('DeviceClass') == 'iPhone']
            if len(devices) != 1:
                raise RuntimeError('请只连接一台已解锁并信任此电脑的 iPhone')
            self.worker = await asyncio.create_subprocess_exec(sys.executable, '-u', str(ROOT/'device_worker.py'), '--native', '--udid', devices[0]['Identifier'], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None)
            try:
                result = await self.response()
                if not result.get('ready'):
                    raise RuntimeError('设备未就绪')
                self.status.update(connected=True, error='', device=devices[0]['ProductVersion'])
            except Exception:
                await self.close_worker()
                raise

    async def send(self, command):
        pending = asyncio.create_task(self.exchange(command))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await pending
            raise

    async def exchange(self, command):
        async with self.lock:
            if not self.status['connected'] or not self.worker or self.worker.returncode is not None:
                raise RuntimeError('请先连接 iPhone')
            try:
                self.worker.stdin.write((json.dumps(command)+'\n').encode())
                await self.worker.stdin.drain()
                await self.response()
            except Exception:
                await self.close_worker()
                raise

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task = None
        self.gate.set()
        self.status['mode'] = 'stopped'

    async def play(self):
        try:
            previous = 0
            for sample in self.route['samples']:
                remaining = sample['t'] - previous
                while remaining > 0:
                    await self.gate.wait()
                    start = asyncio.get_running_loop().time()
                    await asyncio.sleep(min(0.1, remaining))
                    if self.gate.is_set():
                        remaining -= asyncio.get_running_loop().time() - start
                await self.gate.wait()
                await self.send({'action': 'set', 'lat': sample['lat'], 'lon': sample['lon']})
                self.status.update(sent=self.status['sent']+1, elapsed=sample['t'], segment=sample.get('segment', 0)+1, position=[sample['lat'], sample['lon']])
                previous = sample['t']
            self.status['mode'] = 'completed'
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.status.update(mode='error', error=str(error))


controller = Controller()
actions = asyncio.Lock()


@contextlib.asynccontextmanager
async def lifespan(app):
    yield
    await controller.stop()
    if controller.status['connected']:
        with contextlib.suppress(Exception):
            await controller.send({'action': 'clear'})
    await controller.close_worker()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def local_only(request: Request, call_next):
    from fastapi.responses import JSONResponse
    if request.headers.get('host') not in [f'127.0.0.1:{PORT}', f'localhost:{PORT}']:
        return JSONResponse({'detail': '本地访问限定'}, status_code=403)
    if request.method == 'POST' and request.headers.get('x-local-token') != TOKEN:
        return JSONResponse({'detail': '请重新打开页面'}, status_code=403)
    return await call_next(request)


@app.get('/')
async def index():
    return HTMLResponse((ROOT/'static/index.html').read_text().replace('__TOKEN__', TOKEN), headers={'Cache-Control': 'no-store'})


@app.get('/api/status')
async def status():
    if controller.worker and controller.worker.returncode is not None:
        controller.status.update(connected=False, error='设备连接已关闭')
    return controller.status


@app.post('/api/{action}')
async def command(action: str, request: Request):
    async with actions:
        try:
            data = await request.json()
            if action == 'preview':
                return generate(data)
            if action == 'connect':
                await controller.connect()
            elif action == 'start':
                if not controller.status['connected']:
                    raise ValueError('请先连接 iPhone')
                route = generate(data)
                await controller.stop()
                controller.route = route
                controller.status.update(mode='playing', sent=0, total=len(route['samples']), elapsed=0, error='')
                controller.task = asyncio.create_task(controller.play())
            elif action == 'pause':
                if controller.status['mode'] != 'playing':
                    raise ValueError('当前没有正在发送的轨迹')
                controller.gate.clear()
                controller.status['mode'] = 'paused'
                async with controller.lock:
                    pass
            elif action == 'resume':
                if controller.status['mode'] != 'paused':
                    raise ValueError('当前没有暂停的轨迹')
                controller.status['mode'] = 'playing'
                controller.gate.set()
            elif action == 'stop':
                await controller.stop()
            elif action == 'clear':
                await controller.stop()
                await controller.connect()
                await controller.send({'action': 'clear'})
                controller.status.update(mode='cleared', position=None, error='')
            else:
                raise ValueError('未知操作')
            return controller.status
        except Exception as error:
            raise HTTPException(400, str(error) or type(error).__name__)


app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
