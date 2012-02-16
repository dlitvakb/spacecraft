# -*- coding: utf-8 *-*
from twisted.internet.protocol import ClientFactory
from twisted.internet import reactor

import pygame
import euclid

import spacecraft


class Scene:

    def __init__(self, screen):
        self.matrix = euclid.Matrix3.new_identity()
        self.screen = screen
        self.size = self.screen.get_size()

    def rotate(self, radians):
        self.matrix.rotate(radians)

    def translate(self, x, y):
        self.matrix.translate(x, y)

    def scale(self, size):
        self.matrix.scale(size, size)

    def to_screen(self, x, y):
        p = self.matrix * euclid.Point2(x, y)
        p.y = self.size[1] - p.y
        return int(p.x), int(p.y)

    def lookat(self, x, y, width):
        self.matrix = euclid.Matrix3.new_identity()
        self.scale(self.size[0] / float(width))
        height = int(1. * self.size[1] * width / self.size[0])
        self.translate(width / 2 - x, height / 2 - y)


class Monitor(spacecraft.server.ClientBase):

    def __init__(self):
        self.messages = []
        self.font = pygame.font.Font(None, 18)

    def messageReceived(self, message):
        kind = message.get("type", None)
        if kind == "time":
            self.update(self.messages + [message])
            self.messages = []
        elif kind == "map_description":
            x = message["xsize"]
            y = message["ysize"]
            self.scene.lookat(x / 2, y / 2, x)
        else:
            self.messages.append(message)

    def update(self, messages):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.transport.loseConnection()

        self.screen.fill((0, 0, 0))
        for msg in messages:
            kind = msg.get("type", None)
            if kind == "player":
                color = (255, 0, 0)
                position = self.scene.to_screen(msg["x"], msg["y"])
                pygame.draw.circle(self.screen, color, position, 5)
            elif kind == "time":
                text = self.font.render("Step: %s" % (msg["step"],),
                    True, (255, 255, 255))
                where = text.get_rect()
                where.bottom = self.screen.get_height()
                where.left = 0
                self.screen.blit(text, where)
        pygame.display.flip()

    def connectionLost(self, reason):
        reactor.stop()


class MonitorFactory(ClientFactory):
    protocol = Monitor

    def __init__(self, screen):
        self.screen = screen

    def buildProtocol(self, addr):
        proto = ClientFactory.buildProtocol(self, addr)
        proto.screen = self.screen
        proto.scene = Scene(self.screen)
        return proto

    def clientConnectionFailed(self, connector, reason):
        reactor.stop()


def main():
    pygame.init()
    pygame.font.init()
    size = [700, 500]
    screen = pygame.display.set_mode(size)

    reactor.connectTCP("localhost", 11105, MonitorFactory(screen))


if __name__ == "__main__":
    reactor.callWhenRunning(main)
    reactor.run()
    pygame.quit()