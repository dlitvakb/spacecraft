# -*- coding: utf-8 *-*
import random
import math
import sys

from Box2D import b2
import Box2D

from twisted.application import service
from twisted.internet import task

from spacecraft import euclid

STATUS_WAITING = "waiting"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"


def trace(func):
    def tracer(frame, event, arg):
        #print event, dir(frame), dir(frame.f_code), frame.f_code.co_name
        #print [ (x, getattr(frame, x)) for x in dir(frame)]
        if "world.py" in frame.f_code.co_filename:
            #print frame.f_code.co_filename + ":" + str(frame.f_lineno), \
            #    frame.f_code.co_name, event
            if event == "ddexception":
                print arg[1]
                print arg[0].message
                for a in arg[0].args:
                    print type(a)
                for a in arg:
                    print type(a), dir(a)

        return tracef[0]

    tracef = [tracer]

    def inner(*args, **kwargs):
        tracef[0] = tracer

        sys.settrace(tracef[0])
        try:
            return func(*args, **kwargs)
        finally:
            tracef[0] = None
    return inner


class Game(service.Service):

    def __init__(self, xsize, ysize, frames=20, start=False):
        self.xsize = xsize
        self.ysize = ysize
        self.timeStep = 1. / frames
        self.vel_iters = 10
        self.pos_iters = 10
        self.step = 0

        self.world = b2.world(gravity=(0, 0), doSleep=True)
        self.clients = []
        self.objects = []
        self.players = []
        self.players_results = []
        self.terrain = []
        self.taken_names = []

        if start:
            self.status = STATUS_RUNNING
        else:
            self.status = STATUS_WAITING
        self.winner = None
        self.update_loop = task.LoopingCall(self.doStep)

    def start_game(self):
        self.status = STATUS_RUNNING
        self.notifyEvent(type="game_status", current=self.status)

    def finish_game(self, winner):
        self.status = STATUS_FINISHED
        self.winner = winner
        self.notifyEvent(type="game_status", current=self.status, winner=self.winner.name,
                         result_table=self.get_result_table())

    def startService(self):
        self.update_loop.start(self.timeStep)

    def stopService(self):
        self.update_loop.stop()

    def notifyEvent(self, **kwargs):
        for client in self.clients:
            client.sendMessage(**kwargs)

    def doStep(self):
        if self.status is STATUS_RUNNING:
            for object in self.objects:
                object.execute()
            self.step_world()
            self.step += 1
        for client in self.clients:
            client.sendUpdate()

    def step_world(self):
        self.world.Step(self.timeStep, self.vel_iters, self.pos_iters)
        self.world.ClearForces()
        contacts = []
        for contact in self.world.contacts:
            if not contact.touching:
                continue
            o1 = contact.fixtureA.body.userData
            o2 = contact.fixtureB.body.userData
            contacts.append((o1, o2))

        for o1, o2 in contacts:
            o1.contact(o2)
            o2.contact(o1)
        # wraparound
        for body in self.world.bodies:
            x, y = body.position
            body.position = (x % self.xsize), (y % self.ysize)

    def get_map_description(self):
        return dict(xsize=self.xsize, ysize=self.ysize,
            terrain=[x.get_description() for x in self.terrain])

    def register_client(self, client):
        self.clients.append(client)

    def register_client_name(self, client, name):
        if name in self.taken_names:
            i = 1
            while True:
                i += 1
                name = '%s %i' % (name, i)
                if name not in self.taken_names:
                    break
        client.name = name  # we override the name
        self.taken_names.append(name)

    def unregister_client(self, client):
        if client in self.clients:
            self.clients.remove(client)

    def register_object(self, obj):
        self.objects.append(obj)

    def unregister_object(self, obj):
        if obj in self.objects:
            self.objects.remove(obj)

    def register_player(self, obj):
        self.register_object(obj)
        self.players.append(obj)
        self.notifyEvent(type="player_joined", id=obj.get_id())

    def register_wall(self, obj):
        self.terrain.append(obj)

    def unregister_player(self, obj):
        self.unregister_object(obj)
        if obj in self.players:
            self.players.remove(obj)
            self.players_results.append((obj.frags, obj.hits, obj.name))
        self.notifyEvent(type="player_died", id=obj.get_id())
        if len(self.players) == 1:
            self.notifyEvent(type="player_won", id=self.players[0].get_id())
            self.finish_game(self.players[0])

    def get_result_table(self):
        results = self.players_results[:]
        results.append((self.winner.frags, self.winner.hits, self.winner.name))
        results.sort(reverse=True)
        msgs = []
        for frags, hits, name in results:
            msgs.append('%s: %i frags, %i hits' % (name, frags, hits))
        return msgs


class ObjectBase(object):
    name = "unknown"

    def __init__(self, map, x=None, y=None):
        self.map = map
        self.create_body(x, y)

    def create_body(self, x, y):
        raise NotImplementedError()

    def get_type(self):
        return "object"

    def get_id(self):
        return id(self)

    def get_full_position(self):
        """This returns our full position."""
        return dict(
            position=tuple(self.body.position),
            angle=self.body.angle,
            velocity=tuple(self.body.linearVelocity))

    def get_monitor_data(self):
        """This returns all the data there is to return."""
        return self.get_full_position()

    def destroy(self):
        if self.body is not None:
            self.map.world.DestroyBody(self.body)
            self.body = None

    def contact(self, other):
        """This object is in contact with other."""


class PowerUp(ObjectBase):
    radius = 1

    def get_type(self):
        return "powerup"

    def create_body(self, x=None, y=None):
        if x is None:
            x = random.random() * self.map.xsize
        if y is None:
            y = random.random() * self.map.ysize
        self.body = self.map.world.CreateDynamicBody(position=(x, y),
                                                userData=self)
        self.body.CreateCircleFixture(radius=self.radius, density=1)

    def contact(self, other):
        self.destroy()


class EngineForcePowerUp(PowerUp):
    increase = 1.2

    def contact(self, other):
        if isinstance(other, PlayerObject):
            other.max_force *= self.increase
        super(EngineForcePowerUp, self).contact(other)


class RapidFirePowerUp(PowerUp):
    ratio = 5
    duration = 100
    def contact(self, other):
        if isinstance(other, PlayerObject):
            print "reload delay before effect", other.reload_delay
            other.reload_delay /= self.ratio
            print other.reload_delay
            rapid_fire_effect = RapidFireEffect(self.duration, self.ratio)
            other.callbacks.append(rapid_fire_effect.run)
        super(RapidFirePowerUp, self).contact(other)


class RapidFireEffect:
    def __init__(self, duration, ratio):
        self.d = duration
        self.r = ratio

    def run(self, player):
        self.d -= 1
        if self.d == 0:
            print "finish rapid fire"
            player.reload_delay *= self.r
            print "reload delay after finish", player.reload_delay
            return False
        return True


class ProximityMine(PowerUp):
    radius = 4
    bullets = 50
    min_speed = 50
    max_speed = 150

    def get_type(self):
        return "mine"

    def contact(self, other):
        x, y = self.body.position
        for n in range(self.bullets):
            velocity = random.randint(self.min_speed, self.max_speed)
            angle = euclid.Matrix3.new_rotate(2 * math.pi * random.random())
            speedx, speedy = angle * euclid.Vector2(velocity, 0)
            Shrapnel(self.map, x, y, speedx, speedy)
        super(ProximityMine, self).contact(other)


class GpsSensor(object):
    name = 'gps'

    def __init__(self, player):
        self.player = player

    def getReadings(self):
        return self.player.get_full_position()


class StatusSensor(object):
    name = 'status'

    def __init__(self, player):
        self.player = player

    def getReadings(self):
        return dict(
            health=self.player.health,
            throttle=self.player.current_throttle
            )


def distance(p1, p2):
    return abs(euclid.Point2(*p1) - euclid.Point2(*p2))


class ProximitySensorCallback(Box2D.b2QueryCallback):
    def __init__(self, center, radius):
        self.result = []
        self.center = center
        self.radius = radius
        Box2D.b2QueryCallback.__init__(self)

    def ReportFixture(self, fixture):
        body = fixture.body
        if distance(self.center, body.position) < self.radius:
            self.result.append(body.userData)
        # Continue the query by returning True
        return True


class ProximitySensor(object):
    name = 'proximity'
    radius = 30

    def __init__(self, player):
        self.player = player

    def getReadings(self):
        p = self.player.body.position
        aabb = Box2D.b2AABB(
            lowerBound=p - (self.radius, self.radius),
            upperBound=p + (self.radius, self.radius))

        # Query the world for overlapping shapes.
        query = ProximitySensorCallback(p, self.radius)
        self.player.map.world.QueryAABB(query, aabb)
        return [dict(
                object_type=result.get_type(),
                id=result.get_id(),
                **result.get_full_position())
                for result in query.result
                if result is not self.player]


class RayCastCallback(Box2D.b2RayCastCallback):
    """
    This class captures the closest hit shape.
    """
    def __init__(self):
        super(RayCastCallback, self).__init__()
        self.fixture = None

    # Called for each fixture found in the query. You control how the ray
    # proceeds by returning a float that indicates the fractional length of
    # the ray. By returning 0, you set the ray length to zero. By returning
    # the current fraction, you proceed to find the closest point.
    # By returning 1, you continue with the original ray clipping.
    def ReportFixture(self, fixture, point, normal, fraction):
        self.fixture = fixture
        self.point = Box2D.b2Vec2(point)
        self.normal = Box2D.b2Vec2(normal)
        return fraction


class RadarSensor(object):
    name = 'radar'
    steps = 360
    distance = 50

    def __init__(self, player):
        self.player = player

    def getReadings(self):
        ray = euclid.Vector2(self.distance, 0)
        rotate = euclid.Matrix3.new_rotate(2 * math.pi / self.steps)

        readings = {}
        for step in range(self.steps):
            callback = RayCastCallback()

            point1 = self.player.body.position
            point2 = tuple(ray + self.player.body.position)
            ray = rotate * ray
            self.player.map.world.RayCast(callback, point1, point2)
            if callback.fixture is not None:
                object_id = callback.fixture.body.userData.get_id()
                readings[object_id] = dict(
                    object_type=callback.fixture.body.userData.get_type(),
                    id=object_id,
                    **callback.fixture.body.userData.get_full_position())
        return readings.values()


class PlayerObject(ObjectBase):
    # the maximum possible force from the engines in newtons
    max_force = 300
    # the maximum instant turn per step, in radians
    max_turn = math.pi / 8
    # number of steps that it takes for weapon to reload
    reload_delay = 10
    # base health
    health = 100
    callbacks = []

    def __init__(self, map, x=None, y=None):
        super(PlayerObject, self).__init__(map, x, y)
        self.sensors = [GpsSensor(self), ProximitySensor(self),
             StatusSensor(self)]
        self.map.register_player(self)
        self.throttle = 0  # Queued command
        self.turn = 0
        self.fire = 0
        self.reloading = 0
        self.current_throttle = 0  # Current value
        self.hits = 0
        self.frags = 0

    def compute_hit(self, victim):
        if self is not victim:
            self.hits += 1

    def compute_frag(self, victim):
        if self is not victim:
            self.frags += 1

    def get_full_position(self):
        result = super(PlayerObject, self).get_full_position()
        if hasattr(self, 'name'):
            result['name'] = self.name
        return result

    def get_monitor_data(self):
        result = self.get_full_position()
        result['throttle'] = self.current_throttle
        result['health'] = self.health
        return result

    def execute(self):
        body = self.body
        if self.turn:
            # stop any other turning
            self.body.angularVelocity = 0
            body.angle = (body.angle + self.max_turn *
                self.turn) % (2 * math.pi)
            self.turn = 0
        self.current_throttle = self.throttle
        if self.throttle != 0:
            force = euclid.Matrix3.new_rotate(body.angle) * \
                    euclid.Vector2(1, 0) * self.max_force * \
                    self.throttle
            body.ApplyForce(tuple(force), body.position)
            self.throttle = 0
        if self.reloading:
            self.reloading -= 1
        else:
            if self.fire:
                x, y = euclid.Matrix3.new_rotate(body.angle) * \
                    euclid.Vector2(4, 0) + body.position
                speedx, speedy = euclid.Matrix3.new_rotate(body.angle) * \
                    euclid.Vector2(135, 0) + body.linearVelocity
                Bullet(self.map, x, y, speedx, speedy, shooter=self)
                self.reloading = self.reload_delay
                self.fire = 0

        self.run_callbacks()

    def run_callbacks(self):
        """ Runs callbacks

        If callback returns false it won't be run again.
        """
        if self.callbacks:
            new_callbacks = []
            for cb in self.callbacks:
                r = cb(self)
                if r:
                    new_callbacks.append(cb)
            self.callbacks = new_callbacks

    def get_type(self):
        return "player"

    def create_body(self, x=None, y=None):
        if x is None:
            x = random.random() * self.map.xsize
        if y is None:
            y = random.random() * self.map.ysize
        self.body = self.map.world.CreateDynamicBody(position=(x, y),
                                                userData=self)
        self.body.CreateCircleFixture(radius=2, density=1)

    def destroy(self):
        if self.body is not None:
            super(PlayerObject, self).destroy()
            self.map.unregister_player(self)

    def take_damage(self, damage, callback_hit=None, callback_frag=None):
        """reduces healh, and also returns True if killed"""
        self.health -= damage
        if callable(callback_hit):
            callback_hit()
        if self.health < 0:
            if callable(callback_frag):
                callback_frag()
            self.destroy()

    def getReadings(self):
        if self.body is None:
            return {}
        return dict((s.name, s.getReadings()) for s in self.sensors)


class Bullet(ObjectBase):
    total_ttl = 100
    damage = 10

    def __init__(self, map, x, y, speedx=None, speedy=None, shooter=None):
        self.map = map
        self.shooter = shooter
        self.ttl = self.total_ttl
        self.create_body(x, y, speedx, speedy)
        self.map.register_object(self)

    def execute(self):
        self.ttl -= 1
        if self.ttl <= 0:
            self.destroy()

    def get_type(self):
        return "bullet"

    def create_body(self, x, y, speedx=None, speedy=None):
        if speedx is None:
            speedx = random.random() * self.map.xsize
        if speedy is None:
            speedy = random.random() * self.map.ysize
        self.body = self.map.world.CreateDynamicBody(position=(x, y),
                                                userData=self, bullet=True)
        self.body.CreateCircleFixture(radius=1, density=1)
        self.body.linearVelocity = speedx, speedy

    def contact(self, other):
        if isinstance(other, PlayerObject):
            shooter = getattr(self, 'shooter', None)
            callbacks = {}
            if shooter:
                callbacks['callback_hit'] = lambda: shooter.compute_hit(other)
                callbacks['callback_frag'] = lambda: shooter.compute_frag(other)
            other.take_damage(self.damage, **callbacks)
        self.destroy()
        super(Bullet, self).contact(other)

    def destroy(self):
        self.map.unregister_object(self)
        super(Bullet, self).destroy()


class Shrapnel(Bullet):
    """Like a Bullet, but doesn't disappear in contact with another Shrapnel"""

    def contact(self, other):
        if isinstance(other, PlayerObject):
            other.take_damage(self.damage)
        if not isinstance(other, Shrapnel):
            self.destroy()
        super(Bullet, self).contact(other)
