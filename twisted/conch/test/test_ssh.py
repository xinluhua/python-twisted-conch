# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for L{twisted.conch.ssh}.
"""

import struct

try:
    import Crypto.Cipher.DES3
except ImportError:
    Crypto = None

try:
    import pyasn1
except ImportError:
    pyasn1 = None

from twisted.conch.ssh import common, session, forwarding
from twisted.conch import avatar, error
from twisted.conch.test.keydata import publicRSA_openssh, privateRSA_openssh
from twisted.conch.test.keydata import publicDSA_openssh, privateDSA_openssh
from twisted.cred import portal
from twisted.cred.error import UnauthorizedLogin
from twisted.internet import defer, protocol, reactor
from twisted.internet.error import ProcessTerminated
from twisted.python import failure, log
from twisted.trial import unittest

from twisted.conch.test.test_recvline import LoopbackRelay



class ConchTestRealm(object):
    """
    A realm which expects a particular avatarId to log in once and creates a
    L{ConchTestAvatar} for that request.

    @ivar expectedAvatarID: The only avatarID that this realm will produce an
        avatar for.

    @ivar avatar: A reference to the avatar after it is requested.
    """
    avatar = None

    def __init__(self, expectedAvatarID):
        self.expectedAvatarID = expectedAvatarID


    def requestAvatar(self, avatarID, mind, *interfaces):
        """
        Return a new L{ConchTestAvatar} if the avatarID matches the expected one
        and this is the first avatar request.
        """
        if avatarID == self.expectedAvatarID:
            if self.avatar is not None:
                raise UnauthorizedLogin("Only one login allowed")
            self.avatar = ConchTestAvatar()
            return interfaces[0], self.avatar, self.avatar.logout
        raise UnauthorizedLogin(
            "Only %r may log in, not %r" % (self.expectedAvatarID, avatarID))



class ConchTestAvatar(avatar.ConchUser):
    """
    An avatar against which various SSH features can be tested.

    @ivar loggedOut: A flag indicating whether the avatar logout method has been
        called.
    """
    loggedOut = False

    def __init__(self):
        avatar.ConchUser.__init__(self)
        self.listeners = {}
        self.globalRequests = {}
        self.channelLookup.update({'session': session.SSHSession,
                        'direct-tcpip':forwarding.openConnectForwardingClient})
        self.subsystemLookup.update({'crazy': CrazySubsystem})


    def global_foo(self, data):
        self.globalRequests['foo'] = data
        return 1


    def global_foo_2(self, data):
        self.globalRequests['foo_2'] = data
        return 1, 'data'


    def global_tcpip_forward(self, data):
        host, port = forwarding.unpackGlobal_tcpip_forward(data)
        try:
            listener = reactor.listenTCP(
                port, forwarding.SSHListenForwardingFactory(
                    self.conn, (host, port),
                    forwarding.SSHListenServerForwardingChannel),
                interface=host)
        except:
            log.err(None, "something went wrong with remote->local forwarding")
            return 0
        else:
            self.listeners[(host, port)] = listener
            return 1


    def global_cancel_tcpip_forward(self, data):
        host, port = forwarding.unpackGlobal_tcpip_forward(data)
        listener = self.listeners.get((host, port), None)
        if not listener:
            return 0
        del self.listeners[(host, port)]
        listener.stopListening()
        return 1


    def logout(self):
        self.loggedOut = True
        for listener in self.listeners.values():
            log.msg('stopListening %s' % listener)
            listener.stopListening()



class ConchSessionForTestAvatar(object):
    """
    An ISession adapter for ConchTestAvatar.
    """
    def __init__(self, avatar):
        """
        Initialize the session and create a reference to it on the avatar for
        later inspection.
        """
        self.avatar = avatar
        self.avatar._testSession = self
        self.cmd = None
        self.proto = None
        self.ptyReq = False
        self.eof = 0
        self.onClose = defer.Deferred()


    def getPty(self, term, windowSize, attrs):
        log.msg('pty req')
        self._terminalType = term
        self._windowSize = windowSize
        self.ptyReq = True


    def openShell(self, proto):
        log.msg('opening shell')
        self.proto = proto
        EchoTransport(proto)
        self.cmd = 'shell'


    def execCommand(self, proto, cmd):
        self.cmd = cmd
        self.proto = proto
        f = cmd.split()[0]
        if f == 'false':
            t = FalseTransport(proto)
            # Avoid disconnecting this immediately.  If the channel is closed
            # before execCommand even returns the caller gets confused.
            reactor.callLater(0, t.loseConnection)
        elif f == 'echo':
            t = EchoTransport(proto)
            t.write(cmd[5:])
            t.loseConnection()
        elif f == 'secho':
            t = SuperEchoTransport(proto)
            t.write(cmd[6:])
            t.loseConnection()
        elif f == 'eecho':
            t = ErrEchoTransport(proto)
            t.write(cmd[6:])
            t.loseConnection()
        else:
            raise error.ConchError('bad exec')
        self.avatar.conn.transport.expectedLoseConnection = 1


    def eofReceived(self):
        self.eof = 1


    def closed(self):
        log.msg('closed cmd "%s"' % self.cmd)
        self.remoteWindowLeftAtClose = self.proto.session.remoteWindowLeft
        self.onClose.callback(None)

from twisted.python import components
components.registerAdapter(ConchSessionForTestAvatar, ConchTestAvatar, session.ISession)

class CrazySubsystem(protocol.Protocol):

    def __init__(self, *args, **kw):
        pass

    def connectionMade(self):
        """
        good ... good
        """



class FalseTransport:
    """
    False transport should act like a /bin/false execution, i.e. just exit with
    nonzero status, writing nothing to the terminal.

    @ivar proto: The protocol associated with this transport.
    @ivar closed: A flag tracking whether C{loseConnection} has been called yet.
    """

    def __init__(self, p):
        """
        @type p L{twisted.conch.ssh.session.SSHSessionProcessProtocol} instance
        """
        self.proto = p
        p.makeConnection(self)
        self.closed = 0


    def loseConnection(self):
        """
        Disconnect the protocol associated with this transport.
        """
        if self.closed:
            return
        self.closed = 1
        self.proto.inConnectionLost()
        self.proto.outConnectionLost()
        self.proto.errConnectionLost()
        self.proto.processEnded(failure.Failure(ProcessTerminated(255, None, None)))



class EchoTransport:

    def __init__(self, p):
        self.proto = p
        p.makeConnection(self)
        self.closed = 0

    def write(self, data):
        log.msg(repr(data))
        self.proto.outReceived(data)
        self.proto.outReceived('\r\n')
        if '\x00' in data: # mimic 'exit' for the shell test
            self.loseConnection()

    def loseConnection(self):
        if self.closed: return
        self.closed = 1
        self.proto.inConnectionLost()
        self.proto.outConnectionLost()
        self.proto.errConnectionLost()
        self.proto.processEnded(failure.Failure(ProcessTerminated(0, None, None)))

class ErrEchoTransport:

    def __init__(self, p):
        self.proto = p
        p.makeConnection(self)
        self.closed = 0

    def write(self, data):
        self.proto.errReceived(data)
        self.proto.errReceived('\r\n')

    def loseConnection(self):
        if self.closed: return
        self.closed = 1
        self.proto.inConnectionLost()
        self.proto.outConnectionLost()
        self.proto.errConnectionLost()
        self.proto.processEnded(failure.Failure(ProcessTerminated(0, None, None)))

class SuperEchoTransport:

    def __init__(self, p):
        self.proto = p
        p.makeConnection(self)
        self.closed = 0

    def write(self, data):
        self.proto.outReceived(data)
        self.proto.outReceived('\r\n')
        self.proto.errReceived(data)
        self.proto.errReceived('\r\n')

    def loseConnection(self):
        if self.closed: return
        self.closed = 1
        self.proto.inConnectionLost()
        self.proto.outConnectionLost()
        self.proto.errConnectionLost()
        self.proto.processEnded(failure.Failure(ProcessTerminated(0, None, None)))


if Crypto is not None and pyasn1 is not None:
    from twisted.conch import checkers
    from twisted.conch.ssh import channel, connection, factory, keys
    from twisted.conch.ssh import transport, userauth

    class UtilityTestCase(unittest.TestCase):
        def testCounter(self):
            c = transport._Counter('\x00\x00', 2)
            for i in xrange(256 * 256):
                self.assertEqual(c(), struct.pack('!H', (i + 1) % (2 ** 16)))
            # It should wrap around, too.
            for i in xrange(256 * 256):
                self.assertEqual(c(), struct.pack('!H', (i + 1) % (2 ** 16)))


    class ConchTestPublicKeyChecker(checkers.SSHPublicKeyDatabase):
        def checkKey(self, credentials):
            blob = keys.Key.fromString(publicDSA_openssh).blob()
            if credentials.username == 'testuser' and credentials.blob == blob:
                return True
            return False


    class ConchTestPasswordChecker:
        credentialInterfaces = checkers.IUsernamePassword,

        def requestAvatarId(self, credentials):
            if credentials.username == 'testuser' and credentials.password == 'testpass':
                return defer.succeed(credentials.username)
            return defer.fail(Exception("Bad credentials"))


    class ConchTestSSHChecker(checkers.SSHProtocolChecker):

        def areDone(self, avatarId):
            if avatarId != 'testuser' or len(self.successfulCredentials[avatarId]) < 2:
                return False
            return True

    class ConchTestServerFactory(factory.SSHFactory):
        noisy = 0

        services = {
            'ssh-userauth':userauth.SSHUserAuthServer,
            'ssh-connection':connection.SSHConnection
        }

        def buildProtocol(self, addr):
            proto = ConchTestServer()
            proto.supportedPublicKeys = self.privateKeys.keys()
            proto.factory = self

            if hasattr(self, 'expectedLoseConnection'):
                proto.expectedLoseConnection = self.expectedLoseConnection

            self.proto = proto
            return proto

        def getPublicKeys(self):
            return {
                'ssh-rsa': keys.Key.fromString(publicRSA_openssh),
                'ssh-dss': keys.Key.fromString(publicDSA_openssh)
            }

        def getPrivateKeys(self):
            return {
                'ssh-rsa': keys.Key.fromString(privateRSA_openssh),
                'ssh-dss': keys.Key.fromString(privateDSA_openssh)
            }

        def getPrimes(self):
            return {
                2048:[(transport.DH_GENERATOR, transport.DH_PRIME)]
            }

        def getService(self, trans, name):
            return factory.SSHFactory.getService(self, trans, name)

    class ConchTestBase:

        done = 0

        def connectionLost(self, reason):
            if self.done:
                return
            if not hasattr(self,'expectedLoseConnection'):
                unittest.fail('unexpectedly lost connection %s\n%s' % (self, reason))
            self.done = 1

        def receiveError(self, reasonCode, desc):
            self.expectedLoseConnection = 1
            # Some versions of OpenSSH (for example, OpenSSH_5.3p1) will
            # send a DISCONNECT_BY_APPLICATION error before closing the
            # connection.  Other, older versions (for example,
            # OpenSSH_5.1p1), won't.  So accept this particular error here,
            # but no others.
            if reasonCode != transport.DISCONNECT_BY_APPLICATION:
                log.err(
                    Exception(
                        'got disconnect for %s: reason %s, desc: %s' % (
                            self, reasonCode, desc)))
            self.loseConnection()

        def receiveUnimplemented(self, seqID):
            unittest.fail('got unimplemented: seqid %s'  % seqID)
            self.expectedLoseConnection = 1
            self.loseConnection()

    class ConchTestServer(ConchTestBase, transport.SSHServerTransport):

        def connectionLost(self, reason):
            ConchTestBase.connectionLost(self, reason)
            transport.SSHServerTransport.connectionLost(self, reason)


    class ConchTestClient(ConchTestBase, transport.SSHClientTransport):
        """
        @ivar _channelFactory: A callable which accepts an SSH connection and
            returns a channel which will be attached to a new channel on that
            connection.
        """
        def __init__(self, channelFactory):
            self._channelFactory = channelFactory

        def connectionLost(self, reason):
            ConchTestBase.connectionLost(self, reason)
            transport.SSHClientTransport.connectionLost(self, reason)

        def verifyHostKey(self, key, fp):
            keyMatch = key == keys.Key.fromString(publicRSA_openssh).blob()
            fingerprintMatch = (
                fp == '3d:13:5f:cb:c9:79:8a:93:06:27:65:bc:3d:0b:8f:af')
            if keyMatch and fingerprintMatch:
                return defer.succeed(1)
            return defer.fail(Exception("Key or fingerprint mismatch"))

        def connectionSecure(self):
            self.requestService(ConchTestClientAuth('testuser',
                ConchTestClientConnection(self._channelFactory)))


    class ConchTestClientAuth(userauth.SSHUserAuthClient):

        hasTriedNone = 0 # have we tried the 'none' auth yet?
        canSucceedPublicKey = 0 # can we succed with this yet?
        canSucceedPassword = 0

        def ssh_USERAUTH_SUCCESS(self, packet):
            if not self.canSucceedPassword and self.canSucceedPublicKey:
                unittest.fail('got USERAUTH_SUCESS before password and publickey')
            userauth.SSHUserAuthClient.ssh_USERAUTH_SUCCESS(self, packet)

        def getPassword(self):
            self.canSucceedPassword = 1
            return defer.succeed('testpass')

        def getPrivateKey(self):
            self.canSucceedPublicKey = 1
            return defer.succeed(keys.Key.fromString(privateDSA_openssh))

        def getPublicKey(self):
            return keys.Key.fromString(publicDSA_openssh)


    class ConchTestClientConnection(connection.SSHConnection):
        """
        @ivar _completed: A L{Deferred} which will be fired when the number of
            results collected reaches C{totalResults}.
        """
        name = 'ssh-connection'
        results = 0
        totalResults = 8

        def __init__(self, channelFactory):
            connection.SSHConnection.__init__(self)
            self._channelFactory = channelFactory

        def serviceStarted(self):
            self.openChannel(self._channelFactory(conn=self))


    class SSHTestChannel(channel.SSHChannel):

        def __init__(self, name, opened, *args, **kwargs):
            self.name = name
            self._opened = opened
            self.received = []
            self.receivedExt = []
            self.onClose = defer.Deferred()
            channel.SSHChannel.__init__(self, *args, **kwargs)


        def openFailed(self, reason):
            self._opened.errback(reason)


        def channelOpen(self, ignore):
            self._opened.callback(self)


        def dataReceived(self, data):
            self.received.append(data)


        def extReceived(self, dataType, data):
            if dataType == connection.EXTENDED_DATA_STDERR:
                self.receivedExt.append(data)
            else:
                log.msg("Unrecognized extended data: %r" % (dataType,))


        def request_exit_status(self, status):
            [self.status] = struct.unpack('>L', status)


        def eofReceived(self):
            self.eofCalled = True


        def closed(self):
            self.onClose.callback(None)



class SSHProtocolTestCase(unittest.TestCase):
    """
    Tests for communication between L{SSHServerTransport} and
    L{SSHClientTransport}.
    """

    if not Crypto:
        skip = "can't run w/o PyCrypto"

    if not pyasn1:
        skip = "Cannot run without PyASN1"

    def _ourServerOurClientTest(self, name='session', **kwargs):
        """
        Create a connected SSH client and server protocol pair and return a
        L{Deferred} which fires with an L{SSHTestChannel} instance connected to
        a channel on that SSH connection.
        """
        result = defer.Deferred()
        self.realm = ConchTestRealm('testuser')
        p = portal.Portal(self.realm)
        sshpc = ConchTestSSHChecker()
        sshpc.registerChecker(ConchTestPasswordChecker())
        sshpc.registerChecker(ConchTestPublicKeyChecker())
        p.registerChecker(sshpc)
        fac = ConchTestServerFactory()
        fac.portal = p
        fac.startFactory()
        self.server = fac.buildProtocol(None)
        self.clientTransport = LoopbackRelay(self.server)
        self.client = ConchTestClient(
            lambda conn: SSHTestChannel(name, result, conn=conn, **kwargs))

        self.serverTransport = LoopbackRelay(self.client)

        self.server.makeConnection(self.serverTransport)
        self.client.makeConnection(self.clientTransport)
        return result


    def test_subsystemsAndGlobalRequests(self):
        """
        Run the Conch server against the Conch client.  Set up several different
        channels which exercise different behaviors and wait for them to
        complete.  Verify that the channels with errors log them.
        """
        channel = self._ourServerOurClientTest()

        def cbSubsystem(channel):
            self.channel = channel
            return self.assertFailure(
                channel.conn.sendRequest(
                    channel, 'subsystem', common.NS('not-crazy'), 1),
                Exception)
        channel.addCallback(cbSubsystem)

        def cbNotCrazyFailed(ignored):
            channel = self.channel
            return channel.conn.sendRequest(
                channel, 'subsystem', common.NS('crazy'), 1)
        channel.addCallback(cbNotCrazyFailed)

        def cbGlobalRequests(ignored):
            channel = self.channel
            d1 = channel.conn.sendGlobalRequest('foo', 'bar', 1)

            d2 = channel.conn.sendGlobalRequest('foo-2', 'bar2', 1)
            d2.addCallback(self.assertEqual, 'data')

            d3 = self.assertFailure(
                channel.conn.sendGlobalRequest('bar', 'foo', 1),
                Exception)

            return defer.gatherResults([d1, d2, d3])
        channel.addCallback(cbGlobalRequests)

        def disconnect(ignored):
            self.assertEqual(
                self.realm.avatar.globalRequests,
                {"foo": "bar", "foo_2": "bar2"})
            channel = self.channel
            channel.conn.transport.expectedLoseConnection = True
            channel.conn.serviceStopped()
            channel.loseConnection()
        channel.addCallback(disconnect)

        return channel


    def test_shell(self):
        """
        L{SSHChannel.sendRequest} can open a shell with a I{pty-req} request,
        specifying a terminal type and window size.
        """
        channel = self._ourServerOurClientTest()

        data = session.packRequest_pty_req('conch-test-term', (24, 80, 0, 0), '')
        def cbChannel(channel):
            self.channel = channel
            return channel.conn.sendRequest(channel, 'pty-req', data, 1)
        channel.addCallback(cbChannel)

        def cbPty(ignored):
            # The server-side object corresponding to our client side channel.
            session = self.realm.avatar.conn.channels[0].session
            self.assertIdentical(session.avatar, self.realm.avatar)
            self.assertEqual(session._terminalType, 'conch-test-term')
            self.assertEqual(session._windowSize, (24, 80, 0, 0))
            self.assertTrue(session.ptyReq)
            channel = self.channel
            return channel.conn.sendRequest(channel, 'shell', '', 1)
        channel.addCallback(cbPty)

        def cbShell(ignored):
            self.channel.write('testing the shell!\x00')
            self.channel.conn.sendEOF(self.channel)
            return defer.gatherResults([
                    self.channel.onClose,
                    self.realm.avatar._testSession.onClose])
        channel.addCallback(cbShell)

        def cbExited(ignored):
            if self.channel.status != 0:
                log.msg(
                    'shell exit status was not 0: %i' % (self.channel.status,))
            self.assertEqual(
                "".join(self.channel.received),
                'testing the shell!\x00\r\n')
            self.assertTrue(self.channel.eofCalled)
            self.assertTrue(
                self.realm.avatar._testSession.eof)
        channel.addCallback(cbExited)
        return channel


    def test_failedExec(self):
        """
        If L{SSHChannel.sendRequest} issues an exec which the server responds to
        with an error, the L{Deferred} it returns fires its errback.
        """
        channel = self._ourServerOurClientTest()

        def cbChannel(channel):
            self.channel = channel
            return self.assertFailure(
                channel.conn.sendRequest(
                    channel, 'exec', common.NS('jumboliah'), 1),
                Exception)
        channel.addCallback(cbChannel)

        def cbFailed(ignored):
            # The server logs this exception when it cannot perform the
            # requested exec.
            errors = self.flushLoggedErrors(error.ConchError)
            self.assertEqual(errors[0].value.args, ('bad exec', None))
        channel.addCallback(cbFailed)
        return channel


    def test_falseChannel(self):
        """
        When the process started by a L{SSHChannel.sendRequest} exec request
        exits, the exit status is reported to the channel.
        """
        channel = self._ourServerOurClientTest()

        def cbChannel(channel):
            self.channel = channel
            return channel.conn.sendRequest(
                channel, 'exec', common.NS('false'), 1)
        channel.addCallback(cbChannel)

        def cbExec(ignored):
            return self.channel.onClose
        channel.addCallback(cbExec)

        def cbClosed(ignored):
            # No data is expected
            self.assertEqual(self.channel.received, [])
            self.assertNotEquals(self.channel.status, 0)
        channel.addCallback(cbClosed)
        return channel


    def test_errorChannel(self):
        """
        Bytes sent over the extended channel for stderr data are delivered to
        the channel's C{extReceived} method.
        """
        channel = self._ourServerOurClientTest(localWindow=4, localMaxPacket=5)

        def cbChannel(channel):
            self.channel = channel
            return channel.conn.sendRequest(
                channel, 'exec', common.NS('eecho hello'), 1)
        channel.addCallback(cbChannel)

        def cbExec(ignored):
            return defer.gatherResults([
                    self.channel.onClose,
                    self.realm.avatar._testSession.onClose])
        channel.addCallback(cbExec)

        def cbClosed(ignored):
            self.assertEqual(self.channel.received, [])
            self.assertEqual("".join(self.channel.receivedExt), "hello\r\n")
            self.assertEqual(self.channel.status, 0)
            self.assertTrue(self.channel.eofCalled)
            self.assertEqual(self.channel.localWindowLeft, 4)
            self.assertEqual(
                self.channel.localWindowLeft,
                self.realm.avatar._testSession.remoteWindowLeftAtClose)
        channel.addCallback(cbClosed)
        return channel


    def test_unknownChannel(self):
        """
        When an attempt is made to open an unknown channel type, the L{Deferred}
        returned by L{SSHChannel.sendRequest} fires its errback.
        """
        d = self.assertFailure(
            self._ourServerOurClientTest('crazy-unknown-channel'), Exception)
        def cbFailed(ignored):
            errors = self.flushLoggedErrors(error.ConchError)
            self.assertEqual(errors[0].value.args, (3, 'unknown channel'))
            self.assertEqual(len(errors), 1)
        d.addCallback(cbFailed)
        return d


    def test_maxPacket(self):
        """
        An L{SSHChannel} can be configured with a maximum packet size to
        receive.
        """
        # localWindow needs to be at least 11 otherwise the assertion about it
        # in cbClosed is invalid.
        channel = self._ourServerOurClientTest(
            localWindow=11, localMaxPacket=1)

        def cbChannel(channel):
            self.channel = channel
            return channel.conn.sendRequest(
                channel, 'exec', common.NS('secho hello'), 1)
        channel.addCallback(cbChannel)

        def cbExec(ignored):
            return self.channel.onClose
        channel.addCallback(cbExec)

        def cbClosed(ignored):
            self.assertEqual(self.channel.status, 0)
            self.assertEqual("".join(self.channel.received), "hello\r\n")
            self.assertEqual("".join(self.channel.receivedExt), "hello\r\n")
            self.assertEqual(self.channel.localWindowLeft, 11)
            self.assertTrue(self.channel.eofCalled)
        channel.addCallback(cbClosed)
        return channel


    def test_echo(self):
        """
        Normal standard out bytes are sent to the channel's C{dataReceived}
        method.
        """
        channel = self._ourServerOurClientTest(localWindow=4, localMaxPacket=5)

        def cbChannel(channel):
            self.channel = channel
            return channel.conn.sendRequest(
                channel, 'exec', common.NS('echo hello'), 1)
        channel.addCallback(cbChannel)

        def cbEcho(ignored):
            return defer.gatherResults([
                    self.channel.onClose,
                    self.realm.avatar._testSession.onClose])
        channel.addCallback(cbEcho)

        def cbClosed(ignored):
            self.assertEqual(self.channel.status, 0)
            self.assertEqual("".join(self.channel.received), "hello\r\n")
            self.assertEqual(self.channel.localWindowLeft, 4)
            self.assertTrue(self.channel.eofCalled)
            self.assertEqual(
                self.channel.localWindowLeft,
                self.realm.avatar._testSession.remoteWindowLeftAtClose)
        channel.addCallback(cbClosed)
        return channel



class TestSSHFactory(unittest.TestCase):

    if not Crypto:
        skip = "can't run w/o PyCrypto"

    if not pyasn1:
        skip = "Cannot run without PyASN1"

    def makeSSHFactory(self, primes=None):
        sshFactory = factory.SSHFactory()
        gpk = lambda: {'ssh-rsa' : keys.Key(None)}
        sshFactory.getPrimes = lambda: primes
        sshFactory.getPublicKeys = sshFactory.getPrivateKeys = gpk
        sshFactory.startFactory()
        return sshFactory


    def test_buildProtocol(self):
        """
        By default, buildProtocol() constructs an instance of
        SSHServerTransport.
        """
        factory = self.makeSSHFactory()
        protocol = factory.buildProtocol(None)
        self.assertIsInstance(protocol, transport.SSHServerTransport)


    def test_buildProtocolRespectsProtocol(self):
        """
        buildProtocol() calls 'self.protocol()' to construct a protocol
        instance.
        """
        calls = []
        def makeProtocol(*args):
            calls.append(args)
            return transport.SSHServerTransport()
        factory = self.makeSSHFactory()
        factory.protocol = makeProtocol
        factory.buildProtocol(None)
        self.assertEqual([()], calls)


    def test_multipleFactories(self):
        f1 = self.makeSSHFactory(primes=None)
        f2 = self.makeSSHFactory(primes={1:(2,3)})
        p1 = f1.buildProtocol(None)
        p2 = f2.buildProtocol(None)
        self.failIf('diffie-hellman-group-exchange-sha1' in p1.supportedKeyExchanges,
                p1.supportedKeyExchanges)
        self.failUnless('diffie-hellman-group-exchange-sha1' in p2.supportedKeyExchanges,
                p2.supportedKeyExchanges)



class MPTestCase(unittest.TestCase):
    """
    Tests for L{common.getMP}.

    @cvar getMP: a method providing a MP parser.
    @type getMP: C{callable}
    """
    getMP = staticmethod(common.getMP)

    if not Crypto:
        skip = "can't run w/o PyCrypto"

    if not pyasn1:
        skip = "Cannot run without PyASN1"


    def test_getMP(self):
        """
        L{common.getMP} should parse the a multiple precision integer from a
        string: a 4-byte length followed by length bytes of the integer.
        """
        self.assertEqual(
            self.getMP('\x00\x00\x00\x04\x00\x00\x00\x01'),
            (1, ''))


    def test_getMPBigInteger(self):
        """
        L{common.getMP} should be able to parse a big enough integer
        (that doesn't fit on one byte).
        """
        self.assertEqual(
            self.getMP('\x00\x00\x00\x04\x01\x02\x03\x04'),
            (16909060, ''))


    def test_multipleGetMP(self):
        """
        L{common.getMP} has the ability to parse multiple integer in the same
        string.
        """
        self.assertEqual(
            self.getMP('\x00\x00\x00\x04\x00\x00\x00\x01'
                       '\x00\x00\x00\x04\x00\x00\x00\x02', 2),
            (1, 2, ''))


    def test_getMPRemainingData(self):
        """
        When more data than needed is sent to L{common.getMP}, it should return
        the remaining data.
        """
        self.assertEqual(
            self.getMP('\x00\x00\x00\x04\x00\x00\x00\x01foo'),
            (1, 'foo'))


    def test_notEnoughData(self):
        """
        When the string passed to L{common.getMP} doesn't even make 5 bytes,
        it should raise a L{struct.error}.
        """
        self.assertRaises(struct.error, self.getMP, '\x02\x00')



class PyMPTestCase(MPTestCase):
    """
    Tests for the python implementation of L{common.getMP}.
    """
    getMP = staticmethod(common.getMP_py)



class GMPYMPTestCase(MPTestCase):
    """
    Tests for the gmpy implementation of L{common.getMP}.
    """
    getMP = staticmethod(common._fastgetMP)


class BuiltinPowHackTestCase(unittest.TestCase):
    """
    Tests that the builtin pow method is still correct after
    L{twisted.conch.ssh.common} monkeypatches it to use gmpy.
    """

    def test_floatBase(self):
        """
        pow gives the correct result when passed a base of type float with a
        non-integer value.
        """
        self.assertEqual(6.25, pow(2.5, 2))

    def test_intBase(self):
        """
        pow gives the correct result when passed a base of type int.
        """
        self.assertEqual(81, pow(3, 4))

    def test_longBase(self):
        """
        pow gives the correct result when passed a base of type long.
        """
        self.assertEqual(81, pow(3, 4))

    def test_mpzBase(self):
        """
        pow gives the correct result when passed a base of type gmpy.mpz.
        """
        if gmpy is None:
            raise unittest.SkipTest('gmpy not available')
        self.assertEqual(81, pow(gmpy.mpz(3), 4))


try:
    import gmpy
except ImportError:
    GMPYMPTestCase.skip = "gmpy not available"
    gmpy = None
