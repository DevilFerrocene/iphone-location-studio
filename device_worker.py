import asyncio
import json
import sys

from typer_injector import InjectingTyper
from pymobiledevice3.cli.cli_common import ServiceProviderDep, async_command
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

cli = InjectingTyper()


def reply(value):
    print(json.dumps(value), flush=True)


@cli.command()
@async_command
async def serve(service_provider: ServiceProviderDep):
    async with DvtProvider(service_provider) as dvt, LocationSimulation(dvt) as location:
        reply({'ready': True})
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                command = json.loads(line)
                if command['action'] == 'set':
                    await location.set(command['lat'], command['lon'])
                elif command['action'] == 'clear':
                    await location.clear()
                else:
                    raise ValueError('未知设备操作')
                reply({'ok': True})
            except Exception as error:
                reply({'error': str(error)})


if __name__ == '__main__':
    cli()
