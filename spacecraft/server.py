# -*- coding: utf-8 *-*
import json

from twisted.protocols.basic import LineReceiver
from twisted.internet.protocol import Factory
from twisted.application import service, internet
from twisted.python import usage, log
from twisted.internet import reactor
from twisted.web import static, server

from spacecraft import world, map


class ClientBase(LineReceiver):
    """The base class for clients."""
    name = 'define a better name bitch. "name" attr in your client'

    def sendName(self):
        self.sendMessage({'type': 'name', 'value': self.name})

    def lineReceived(self, line):
        try:
            d = self.decode(line)
        except ValueError:
            log.msg("invalid line:", line)
        else:
            if d.get('type', '') == 'name please':
                self.sendName()
            self.messageReceived(d)

    def sendMessage(self, *args, **kwargs):
        if args and kwargs:
            raise TypeError("cant use both args and kwargs.")

        if args and len(args) == 1:
            self.sendLine(self.encode(args[0]))

        if kwargs:
            self.sendLine(self.encode(kwargs))

    def decode(self, data):
        return json.loads(data)

    def encode(self, message):
        return json.dumps(message)

    def messageReceived(self, message):
        raise NotImplementedError()

    def command(self, msg_type, **kwargs):
        kwargs["type"] = msg_type
        self.sendMessage(kwargs)


class Client(ClientBase):
    """The server representation of a client."""
    name = 'unregistered name'

    def connectionLost(self, reason):
        log.msg("client connection lost:", (self.addr,))
        self.unregister()

    def unregister(self):
        self.map.unregister_client(self)

    def register(self, map):
        self.map = map
        map.register_client(self)

    def execute(self):
        pass

    def sendUpdate(self):
        self.sendMessage(type="time", step=self.map.step)

    def messageReceived(self, message):
        msg_type = message.get("type", None)
        if msg_type is None:
            return
        meth = getattr(self, "do_" + msg_type, None)

        if meth is None:
            log.msg("Unknown message type:", msg_type)
            return

        meth(message)

    def sendHello(self):
        if self.transport:
            m = self.map.get_map_description()
            m['type'] = "map_description"
            self.sendMessage(m)


class ClientFactory(Factory):
    def __init__(self, map):
        self.map = map

    def buildProtocol(self, addr):
        log.msg("Client connected from:", (addr,))
        protocol = Factory.buildProtocol(self, addr)
        protocol.register(self.map)
        protocol.addr = addr
        return protocol


class Player(Client):
    def register(self, map):
        Client.register(self, map)
        reactor.callLater(0, self._register)

    def _register(self):
        self.object = world.PlayerObject(self.map)
        reactor.callLater(0, self.sendHello)

    def unregister(self):
        Client.unregister(self)
        self.object.destroy()

    def do_throttle(self, message):
        value = message.get("value", 0)
        if not isinstance(value, (int, float)):
            log.msg("Bad throttle message:", message)

        self.object.throttle = max(0, min(1, value))

    def do_turn(self, message):
        value = message.get("value", 0)
        if not isinstance(value, (int, float)):
            log.msg("Bad turn message:", message)

        self.object.turn = max(-1, min(1, value))

    def do_fire(self, message):
        self.object.fire = 1

    def sendUpdate(self):
        if hasattr(self, 'object'):
            self.sendMessage(type="sensor", **self.object.getReadings())
        self.sendMessage(type="time", step=self.map.step)

    def do_name(self, msg):
        name = msg['value']
        self.object.name = name # so nobody complains
        self.object.map.register_client_name(self.object, name)

    def sendHello(self):
        Client.sendHello(self)
        if self.transport:
            self.sendMessage({'type': 'name please'})


class PlayerFactory(ClientFactory):
    protocol = Player


class Monitor(Client):

    def register(self, map):
        Client.register(self, map)
        reactor.callLater(0, self.sendHello)

    def sendUpdate(self):
        for body in self.map.world.bodies:
            self.sendMessage(dict(
                type="monitor",
                object_type=body.userData.get_type(),
                **body.userData.get_monitor_data()))
        self.sendMessage(type="time", step=self.map.step)

    def do_start_game(self, message):
        self.map.start_game()


class MonitorFactory(ClientFactory):
    protocol = Monitor


class Options(usage.Options):
    optParameters = [
        ["monitorport", "m", 11105,
            "The port number to listen on for monitors.", int],
        ["playerport", "p", 11106,
            "The port number to listen on for players.", int],
        ["httpport", "p", 11107,
            "The port number to listen on for http requests.", int],

        ["xsize", "x", 100,
            "The map x size.", int],
        ["ysize", "y", 100,
            "The map y size.", int],
        ["start", "s", False,
            "Put the game in running mode as soon as the server starts.""",
            bool],
        ["map", "", "",
            "Start with this map.", str],

        ]


def makeService(options):
    root_service = service.MultiService()

    game = world.Game(options["xsize"], options["ysize"],
        start=options["start"])
    if options["map"]:
        maploader = map.MapLoader(options["map"])
        maploader.setup_map(game)

    game.setServiceParent(root_service)

    monitor_service = internet.TCPServer(
        options['monitorport'], MonitorFactory(game))
    monitor_service.setName("monitors")
    monitor_service.setServiceParent(root_service)

    player_service = internet.TCPServer(
        options['playerport'], PlayerFactory(game))
    player_service.setName("players")
    player_service.setServiceParent(root_service)

    # add web service
    root_resource = static.File("static/")
    site = server.Site(root_resource)
    web_service = internet.TCPServer(options['httpport'], site)
    web_service.setServiceParent(root_service)

    return root_service
