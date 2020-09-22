from enum import Enum
import logging
import asyncio
from joycontrol.controller import Controller
from joycontrol.controller_state import ControllerState, StickState, button_push
from joycontrol.memory import FlashMemory
from joycontrol.protocol import ControllerProtocol
from joycontrol.server import create_hid_server

class ControllerStick(str, Enum):
    l_stick = "l_stick"
    r_stick = "r_stick"

class ControllerAxis(str, Enum):
    x_axis = "x_axis"
    y_axis = "y_axis"

class ControllerButton(str, Enum):
    y = 'y'
    x = 'x'
    b = 'b'
    a = 'a'
    r = 'r'
    zr = 'zr'
    minus = 'minus'
    plus = 'plus'
    r_stick = 'r_stick'
    l_stick = 'l_stick'
    home = 'home'
    capture = 'capture'
    down = 'down'
    up = 'up'
    right = 'right'
    left = 'left'
    l = 'l'
    zl = 'zl'
    sr = 'sr'
    sl = 'sl'


class SwitchControllerService:
    def __init__(self):
        self.controller_state: ControllerState = None
        self.transport = None
        self.script_task = None
        self.is_script_running = False
        self.available_buttons = None
        self.available_sticks = {'ls', 'rs'}

    async def disconnect(self):
        if self.is_connected():
            await self.transport.close()

        self.transport = None

    async def connect(self, controller_type: str, reconnect_address: str, spi_firm: bytes):
        if spi_firm is None:
            spi_flash = FlashMemory()
        else:
            spi_flash = FlashMemory(spi_flash_memory_data = spi_firm)
        lib_controller_type = Controller.from_arg(controller_type)

        def create_controller_protocol():
            return ControllerProtocol(lib_controller_type, spi_flash=spi_flash)

        factory = create_controller_protocol
        transport, protocol = await create_hid_server(factory, reconnect_bt_addr=reconnect_address)
        controller_state = protocol.get_controller_state()
        self.controller_state = controller_state
        self.transport = transport
        self.available_buttons = controller_state.button_state.get_available_buttons()

        return transport._itr_sock.getpeername()[0]

    async def run_script(self, script: str):
        if self.script_task and not self.script_task.done():
            return
        if self.is_connected():
            self.script_task = asyncio.create_task(self.script_runner(script))
            self.is_script_running = True
        else:
            print("Not connected")

    async def cancel_script(self):
        self.is_script_running = False

    def script_status(self):
        return self.script_task != None and not self.script_task.done()

    async def get_status(self):
        if not self.is_connected():
            return {"connected": "false"}
        else:
            peer = self.transport._itr_sock.getpeername()[0]
            buttonList = self.controller_state.button_state.get_available_buttons()
            button_dict = {b: self.controller_state.button_state.get_button(b) for b in buttonList}
            controller_type = self.controller_state.get_controller().name
            nfc_active = self.controller_state.get_nfc() is not None
            l_stick_dict = convertStickState(self.controller_state.l_stick_state)
            r_stick_dict = convertStickState(self.controller_state.r_stick_state)
            return {"connected": "true",
                    "peer": peer,
                    "controller_type": controller_type,
                    "buttons": button_dict,
                    "nfc_active": nfc_active,
                    "left_stick": l_stick_dict,
                    "right_stick": r_stick_dict
                    }

    async def press_controller_button(self, button: str):
        if not self.is_connected():
            return
        self.controller_state.button_state.set_button(button, pushed=True)
        await self.controller_state.send()

    async def release_controller_button(self, button: str):
        if not self.is_connected():
            return
        self.controller_state.button_state.set_button(button, pushed=False)
        await self.controller_state.send()

    async def set_stick_axis(self, stick: ControllerStick, axis: ControllerAxis, value: int):
        if not self.is_connected():
            return
        if stick == ControllerStick.l_stick:
            stick_to_change = self.controller_state.l_stick_state
        if stick == ControllerStick.r_stick:
            stick_to_change = self.controller_state.r_stick_state
        if axis == ControllerAxis.x_axis:
            stick_to_change.set_h(value)
        if axis == ControllerAxis.y_axis:
            stick_to_change.set_v(value)
        await self.controller_state.send()

    async def center_stick(self, stick: ControllerStick):
        if not self.is_connected():
            return
        if stick == ControllerStick.l_stick:
            stick_to_change = self.controller_state.l_stick_state
        if stick == ControllerStick.r_stick:
            stick_to_change = self.controller_state.r_stick_state
        stick_to_change.set_center()
        await self.controller_state.send()

    async def set_nfc_data(self, nfc_data: bytes):
        if not self.is_connected():
            return

        old_nfc = self.controller_state.get_nfc()
        if old_nfc is None and nfc_data is None:
            return

        self.controller_state.set_nfc(nfc_data)

    def is_connected(self):
        if self.transport is None:
            return False

        try:
            self.transport._itr_sock.getpeername()[0]
        except:
            return False

        return True

    async def script_runner(self, script: str):
        out = []
        buff = []
        for c in script:
            if c == '\n':
                out.append(''.join(buff))
                buff = []
            else:
                buff.append(c)
        else:
            if buff:
                out.append(''.join(buff))

        user_input = list()
        for line in out:
            line = line.strip()
            if not len(line) or line.startswith('#'):
                continue
            user_input.append(line.lower())

        commands = []
        for i in range(len(user_input)):
            cmd, *args = user_input[i].split()
            if cmd == 'for':
                for _ in range(int(args[0])):
                    until, forcmd = self.forCheck(i, user_input)
                    for get in forcmd:
                        commands.append(get)
            elif self.isCommand(cmd):
                commands.append(user_input[i])

        for command in commands:
            if self.is_script_running == False or self.is_connected() == False:
                return
            await self.pressButton(command)

    async def pressButton(self, *commands):
        for command in commands:
            print(command)
            cmd, *args = command.split()

            if cmd in self.available_buttons:
                await button_push(self.controller_state, cmd)
            elif cmd.isdecimal():
                await asyncio.sleep(float(cmd) / 1000)
            else:
                print('command', cmd, 'not found')

    def forCheck(self, n, user_input):
        commands = []
        until = -1
        for i in range(len(user_input)):
            if i <= n or i <= until:
                continue

            cmd, *args = user_input[i].split()

            if cmd == 'for':
                for _ in range(int(args[0])):
                    until, forcmd = self.forCheck(i, user_input)
                    for get in forcmd:
                        commands.append(get)
            elif cmd == 'next':
                return i, commands
            elif self.isCommand(cmd):
                commands.append(user_input[i])
            else:
                print('command', cmd, 'not found')

    def isCommand(self, cmd):
        return cmd in self.available_buttons or cmd.isdecimal()


def convertStickState(stick_state: StickState):
    if stick_state is None:
        return None
    else:
        return {"x_axis": stick_state.get_h(),
                "y_axis": stick_state.get_v(),
                "is_center": stick_state.is_center()
                }
