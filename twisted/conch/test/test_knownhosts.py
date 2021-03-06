# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for L{twisted.conch.client.knownhosts}.
"""

import os
from binascii import Error as BinasciiError, b2a_base64, a2b_base64

try:
    import Crypto
    import pyasn1
except ImportError:
    skip = "PyCrypto and PyASN1 required for twisted.conch.knownhosts."
else:
    from twisted.conch.ssh.keys import Key, BadKeyError
    from twisted.conch.client.knownhosts import \
        PlainEntry, HashedEntry, KnownHostsFile, UnparsedEntry, ConsoleUI
    from twisted.conch.client import default

from zope.interface.verify import verifyObject

from twisted.python.filepath import FilePath
from twisted.trial.unittest import TestCase
from twisted.internet.defer import Deferred
from twisted.conch.interfaces import IKnownHostEntry
from twisted.conch.error import HostKeyChanged, UserRejectedKey, InvalidEntry


sampleEncodedKey = (
    'AAAAB3NzaC1yc2EAAAABIwAAAQEAsV0VMRbGmzhqxxayLRHmvnFvtyNqgbNKV46dU1bVFB+3y'
    'tNvue4Riqv/SVkPRNwMb7eWH29SviXaBxUhYyzKkDoNUq3rTNnH1Vnif6d6X4JCrUb5d3W+Dm'
    'YClyJrZ5HgD/hUpdSkTRqdbQ2TrvSAxRacj+vHHT4F4dm1bJSewm3B2D8HVOoi/CbVh3dsIiC'
    'dp8VltdZx4qYVfYe2LwVINCbAa3d3tj9ma7RVfw3OH2Mfb+toLd1N5tBQFb7oqTt2nC6I/6Bd'
    '4JwPUld+IEitw/suElq/AIJVQXXujeyiZlea90HE65U2mF1ytr17HTAIT2ySokJWyuBANGACk'
    '6iIaw==')

otherSampleEncodedKey = (
    'AAAAB3NzaC1yc2EAAAABIwAAAIEAwaeCZd3UCuPXhX39+/p9qO028jTF76DMVd9mPvYVDVXuf'
    'WckKZauF7+0b7qm+ChT7kan6BzRVo4++gCVNfAlMzLysSt3ylmOR48tFpAfygg9UCX3DjHz0E'
    'lOOUKh3iifc9aUShD0OPaK3pR5JJ8jfiBfzSYWt/hDi/iZ4igsSs8=')

thirdSampleEncodedKey = (
    'AAAAB3NzaC1yc2EAAAABIwAAAQEAl/TQakPkePlnwCBRPitIVUTg6Z8VzN1en+DGkyo/evkmLw'
    '7o4NWR5qbysk9A9jXW332nxnEuAnbcCam9SHe1su1liVfyIK0+3bdn0YRB0sXIbNEtMs2LtCho'
    '/aV3cXPS+Cf1yut3wvIpaRnAzXxuKPCTXQ7/y0IXa8TwkRBH58OJa3RqfQ/NsSp5SAfdsrHyH2'
    'aitiVKm2jfbTKzSEqOQG/zq4J9GXTkq61gZugory/Tvl5/yPgSnOR6C9jVOMHf27ZPoRtyj9SY'
    '343Hd2QHiIE0KPZJEgCynKeWoKz8v6eTSK8n4rBnaqWdp8MnGZK1WGy05MguXbyCDuTC8AmJXQ'
    '==')

sampleKey = a2b_base64(sampleEncodedKey)
otherSampleKey = a2b_base64(otherSampleEncodedKey)
thirdSampleKey = a2b_base64(thirdSampleEncodedKey)

samplePlaintextLine = (
    "www.twistedmatrix.com ssh-rsa " + sampleEncodedKey + "\n")

otherSamplePlaintextLine = (
    "divmod.com ssh-rsa " + otherSampleEncodedKey + "\n")

sampleHostIPLine = (
    "www.twistedmatrix.com,198.49.126.131 ssh-rsa " + sampleEncodedKey + "\n")

sampleHashedLine = (
    "|1|gJbSEPBG9ZSBoZpHNtZBD1bHKBA=|bQv+0Xa0dByrwkA1EB0E7Xop/Fo= ssh-rsa " +
    sampleEncodedKey + "\n")



class EntryTestsMixin:
    """
    Tests for implementations of L{IKnownHostEntry}.  Subclasses must set the
    'entry' attribute to a provider of that interface, the implementation of
    that interface under test.

    @ivar entry: a provider of L{IKnownHostEntry} with a hostname of
    www.twistedmatrix.com and an RSA key of sampleKey.
    """

    def test_providesInterface(self):
        """
        The given entry should provide IKnownHostEntry.
        """
        verifyObject(IKnownHostEntry, self.entry)


    def test_fromString(self):
        """
        Constructing a plain text entry from an unhashed known_hosts entry will
        result in an L{IKnownHostEntry} provider with 'keyString', 'hostname',
        and 'keyType' attributes.  While outside the interface in question,
        these attributes are held in common by L{PlainEntry} and L{HashedEntry}
        implementations; other implementations should override this method in
        subclasses.
        """
        entry = self.entry
        self.assertEqual(entry.publicKey, Key.fromString(sampleKey))
        self.assertEqual(entry.keyType, "ssh-rsa")


    def test_matchesKey(self):
        """
        L{IKnownHostEntry.matchesKey} checks to see if an entry matches a given
        SSH key.
        """
        twistedmatrixDotCom = Key.fromString(sampleKey)
        divmodDotCom = Key.fromString(otherSampleKey)
        self.assertEqual(
            True,
            self.entry.matchesKey(twistedmatrixDotCom))
        self.assertEqual(
            False,
            self.entry.matchesKey(divmodDotCom))


    def test_matchesHost(self):
        """
        L{IKnownHostEntry.matchesHost} checks to see if an entry matches a
        given hostname.
        """
        self.assertEqual(True, self.entry.matchesHost(
                "www.twistedmatrix.com"))
        self.assertEqual(False, self.entry.matchesHost(
                "www.divmod.com"))



class PlainEntryTests(EntryTestsMixin, TestCase):
    """
    Test cases for L{PlainEntry}.
    """
    plaintextLine = samplePlaintextLine
    hostIPLine = sampleHostIPLine

    def setUp(self):
        """
        Set 'entry' to a sample plain-text entry with sampleKey as its key.
        """
        self.entry = PlainEntry.fromString(self.plaintextLine)


    def test_matchesHostIP(self):
        """
        A "hostname,ip" formatted line will match both the host and the IP.
        """
        self.entry = PlainEntry.fromString(self.hostIPLine)
        self.assertEqual(True, self.entry.matchesHost("198.49.126.131"))
        self.test_matchesHost()


    def test_toString(self):
        """
        L{PlainEntry.toString} generates the serialized OpenSSL format string
        for the entry, sans newline.
        """
        self.assertEqual(self.entry.toString(), self.plaintextLine.rstrip("\n"))
        multiHostEntry = PlainEntry.fromString(self.hostIPLine)
        self.assertEqual(multiHostEntry.toString(), self.hostIPLine.rstrip("\n"))



class PlainTextWithCommentTests(PlainEntryTests):
    """
    Test cases for L{PlainEntry} when parsed from a line with a comment.
    """

    plaintextLine = samplePlaintextLine[:-1] + " plain text comment.\n"
    hostIPLine = sampleHostIPLine[:-1] + " text following host/IP line\n"



class HashedEntryTests(EntryTestsMixin, TestCase):
    """
    Tests for L{HashedEntry}.

    This suite doesn't include any tests for host/IP pairs because hashed
    entries store IP addresses the same way as hostnames and does not support
    comma-separated lists.  (If you hash the IP and host together you can't
    tell if you've got the key already for one or the other.)
    """
    hashedLine = sampleHashedLine

    def setUp(self):
        """
        Set 'entry' to a sample hashed entry for twistedmatrix.com with
        sampleKey as its key.
        """
        self.entry = HashedEntry.fromString(self.hashedLine)


    def test_toString(self):
        """
        L{HashedEntry.toString} generates the serialized OpenSSL format string
        for the entry, sans the newline.
        """
        self.assertEqual(self.entry.toString(), self.hashedLine.rstrip("\n"))



class HashedEntryWithCommentTests(HashedEntryTests):
    """
    Test cases for L{PlainEntry} when parsed from a line with a comment.
    """

    hashedLine = sampleHashedLine[:-1] + " plain text comment.\n"



class UnparsedEntryTests(TestCase, EntryTestsMixin):
    """
    Tests for L{UnparsedEntry}
    """
    def setUp(self):
        """
        Set up the 'entry' to be an unparsed entry for some random text.
        """
        self.entry = UnparsedEntry("    This is a bogus entry.  \n")


    def test_fromString(self):
        """
        Creating an L{UnparsedEntry} should simply record the string it was
        passed.
        """
        self.assertEqual("    This is a bogus entry.  \n",
                         self.entry._string)


    def test_matchesHost(self):
        """
        An unparsed entry can't match any hosts.
        """
        self.assertEqual(False, self.entry.matchesHost("www.twistedmatrix.com"))


    def test_matchesKey(self):
        """
        An unparsed entry can't match any keys.
        """
        self.assertEqual(False, self.entry.matchesKey(Key.fromString(sampleKey)))


    def test_toString(self):
        """
        L{UnparsedEntry.toString} returns its input string, sans trailing newline.
        """
        self.assertEqual("    This is a bogus entry.  ", self.entry.toString())



class ParseErrorTests(TestCase):
    """
    L{HashedEntry.fromString} and L{PlainEntry.fromString} can raise a variety
    of errors depending on misformattings of certain strings.  These tests make
    sure those errors are caught.  Since many of the ways that this can go
    wrong are in the lower-level APIs being invoked by the parsing logic,
    several of these are integration tests with the L{base64} and
    L{twisted.conch.ssh.keys} modules.
    """

    def invalidEntryTest(self, cls):
        """
        If there are fewer than three elements, C{fromString} should raise
        L{InvalidEntry}.
        """
        self.assertRaises(InvalidEntry, cls.fromString, "invalid")


    def notBase64Test(self, cls):
        """
        If the key is not base64, C{fromString} should raise L{BinasciiError}.
        """
        self.assertRaises(BinasciiError, cls.fromString, "x x x")


    def badKeyTest(self, cls, prefix):
        """
        If the key portion of the entry is valid base64, but is not actually an
        SSH key, C{fromString} should raise L{BadKeyError}.
        """
        self.assertRaises(BadKeyError, cls.fromString, ' '.join(
                [prefix, "ssh-rsa", b2a_base64(
                        "Hey, this isn't an SSH key!").strip()]))


    def test_invalidPlainEntry(self):
        """
        If there are fewer than three whitespace-separated elements in an
        entry, L{PlainEntry.fromString} should raise L{InvalidEntry}.
        """
        self.invalidEntryTest(PlainEntry)


    def test_invalidHashedEntry(self):
        """
        If there are fewer than three whitespace-separated elements in an
        entry, or the hostname salt/hash portion has more than two elements,
        L{HashedEntry.fromString} should raise L{InvalidEntry}.
        """
        self.invalidEntryTest(HashedEntry)
        a, b, c = sampleHashedLine.split()
        self.assertRaises(InvalidEntry, HashedEntry.fromString, ' '.join(
                [a + "||", b, c]))


    def test_plainNotBase64(self):
        """
        If the key portion of a plain entry is not decodable as base64,
        C{fromString} should raise L{BinasciiError}.
        """
        self.notBase64Test(PlainEntry)


    def test_hashedNotBase64(self):
        """
        If the key, host salt, or host hash portion of a hashed entry is not
        encoded, it will raise L{BinasciiError}.
        """
        self.notBase64Test(HashedEntry)
        a, b, c = sampleHashedLine.split()
        # Salt not valid base64.
        self.assertRaises(
            BinasciiError, HashedEntry.fromString,
            ' '.join(["|1|x|" + b2a_base64("stuff").strip(), b, c]))
        # Host hash not valid base64.
        self.assertRaises(
            BinasciiError, HashedEntry.fromString,
            ' '.join([HashedEntry.MAGIC + b2a_base64("stuff").strip() + "|x", b, c]))
        # Neither salt nor hash valid base64.
        self.assertRaises(
            BinasciiError, HashedEntry.fromString,
            ' '.join(["|1|x|x", b, c]))


    def test_hashedBadKey(self):
        """
        If the key portion of the entry is valid base64, but is not actually an
        SSH key, C{HashedEntry.fromString} should raise L{BadKeyError}.
        """
        a, b, c = sampleHashedLine.split()
        self.badKeyTest(HashedEntry, a)


    def test_plainBadKey(self):
        """
        If the key portion of the entry is valid base64, but is not actually an
        SSH key, C{PlainEntry.fromString} should raise L{BadKeyError}.
        """
        self.badKeyTest(PlainEntry, "hostname")



class KnownHostsDatabaseTests(TestCase):
    """
    Tests for L{KnownHostsFile}.
    """

    def pathWithContent(self, content):
        """
        Return a FilePath with the given initial content.
        """
        fp = FilePath(self.mktemp())
        fp.setContent(content)
        return fp


    def loadSampleHostsFile(self, content=(
            sampleHashedLine + otherSamplePlaintextLine +
            "\n# That was a blank line.\n"
            "This is just unparseable.\n"
            "|1|This also unparseable.\n")):
        """
        Return a sample hosts file, with keys for www.twistedmatrix.com and
        divmod.com present.
        """
        return KnownHostsFile.fromPath(self.pathWithContent(content))


    def test_loadFromPath(self):
        """
        Loading a L{KnownHostsFile} from a path with six entries in it will
        result in a L{KnownHostsFile} object with six L{IKnownHostEntry}
        providers in it, each of the appropriate type.
        """
        hostsFile = self.loadSampleHostsFile()
        self.assertEqual(len(hostsFile._entries), 6)
        self.assertIsInstance(hostsFile._entries[0], HashedEntry)
        self.assertEqual(True, hostsFile._entries[0].matchesHost(
                "www.twistedmatrix.com"))
        self.assertIsInstance(hostsFile._entries[1], PlainEntry)
        self.assertEqual(True, hostsFile._entries[1].matchesHost(
                "divmod.com"))
        self.assertIsInstance(hostsFile._entries[2], UnparsedEntry)
        self.assertEqual(hostsFile._entries[2].toString(), "")
        self.assertIsInstance(hostsFile._entries[3], UnparsedEntry)
        self.assertEqual(hostsFile._entries[3].toString(),
                         "# That was a blank line.")
        self.assertIsInstance(hostsFile._entries[4], UnparsedEntry)
        self.assertEqual(hostsFile._entries[4].toString(),
                         "This is just unparseable.")
        self.assertIsInstance(hostsFile._entries[5], UnparsedEntry)
        self.assertEqual(hostsFile._entries[5].toString(),
                         "|1|This also unparseable.")


    def test_loadNonExistent(self):
        """
        Loading a L{KnownHostsFile} from a path that does not exist should
        result in an empty L{KnownHostsFile} that will save back to that path.
        """
        pn = self.mktemp()
        knownHostsFile = KnownHostsFile.fromPath(FilePath(pn))
        self.assertEqual([], list(knownHostsFile._entries))
        self.assertEqual(False, FilePath(pn).exists())
        knownHostsFile.save()
        self.assertEqual(True, FilePath(pn).exists())


    def test_loadNonExistentParent(self):
        """
        Loading a L{KnownHostsFile} from a path whose parent directory does not
        exist should result in an empty L{KnownHostsFile} that will save back
        to that path, creating its parent directory(ies) in the process.
        """
        thePath = FilePath(self.mktemp())
        knownHostsPath = thePath.child("foo").child("known_hosts")
        knownHostsFile = KnownHostsFile.fromPath(knownHostsPath)
        knownHostsFile.save()
        knownHostsPath.restat(False)
        self.assertEqual(True, knownHostsPath.exists())


    def test_savingAddsEntry(self):
        """
        L{KnownHostsFile.save()} will write out a new file with any entries
        that have been added.
        """
        path = self.pathWithContent(sampleHashedLine +
                                    otherSamplePlaintextLine)
        knownHostsFile = KnownHostsFile.fromPath(path)
        newEntry = knownHostsFile.addHostKey("some.example.com", Key.fromString(thirdSampleKey))
        expectedContent = (
            sampleHashedLine +
            otherSamplePlaintextLine + HashedEntry.MAGIC +
            b2a_base64(newEntry._hostSalt).strip() + "|" +
            b2a_base64(newEntry._hostHash).strip() + " ssh-rsa " +
            thirdSampleEncodedKey + "\n")

        # Sanity check, let's make sure the base64 API being used for the test
        # isn't inserting spurious newlines.
        self.assertEqual(3, expectedContent.count("\n"))
        knownHostsFile.save()
        self.assertEqual(expectedContent, path.getContent())


    def test_hasPresentKey(self):
        """
        L{KnownHostsFile.hasHostKey} returns C{True} when a key for the given
        hostname is present and matches the expected key.
        """
        hostsFile = self.loadSampleHostsFile()
        self.assertEqual(True, hostsFile.hasHostKey(
                "www.twistedmatrix.com", Key.fromString(sampleKey)))


    def test_hasNonPresentKey(self):
        """
        L{KnownHostsFile.hasHostKey} returns C{False} when a key for the given
        hostname is not present.
        """
        hostsFile = self.loadSampleHostsFile()
        self.assertEqual(False, hostsFile.hasHostKey(
                "non-existent.example.com", Key.fromString(sampleKey)))


    def test_hasKeyMismatch(self):
        """
        L{KnownHostsFile.hasHostKey} raises L{HostKeyChanged} if the host key
        is present, but different from the expected one.  The resulting
        exception should have an offendingEntry indicating the given entry.
        """
        hostsFile = self.loadSampleHostsFile()
        exception = self.assertRaises(
            HostKeyChanged, hostsFile.hasHostKey,
            "www.twistedmatrix.com", Key.fromString(otherSampleKey))
        self.assertEqual(exception.offendingEntry, hostsFile._entries[0])
        self.assertEqual(exception.lineno, 1)
        self.assertEqual(exception.path, hostsFile._savePath)


    def test_addHostKey(self):
        """
        L{KnownHostsFile.addHostKey} adds a new L{HashedEntry} to the host
        file, and returns it.
        """
        hostsFile = self.loadSampleHostsFile()
        aKey = Key.fromString(thirdSampleKey)
        self.assertEqual(False,
                         hostsFile.hasHostKey("somewhere.example.com", aKey))
        newEntry = hostsFile.addHostKey("somewhere.example.com", aKey)

        # The code in OpenSSH requires host salts to be 20 characters long.
        # This is the required length of a SHA-1 HMAC hash, so it's just a
        # sanity check.
        self.assertEqual(20, len(newEntry._hostSalt))
        self.assertEqual(True,
                         newEntry.matchesHost("somewhere.example.com"))
        self.assertEqual(newEntry.keyType, "ssh-rsa")
        self.assertEqual(aKey, newEntry.publicKey)
        self.assertEqual(True,
                         hostsFile.hasHostKey("somewhere.example.com", aKey))


    def test_randomSalts(self):
        """
        L{KnownHostsFile.addHostKey} generates a random salt for each new key,
        so subsequent salts will be different.
        """
        hostsFile = self.loadSampleHostsFile()
        aKey = Key.fromString(thirdSampleKey)
        self.assertNotEqual(
            hostsFile.addHostKey("somewhere.example.com", aKey)._hostSalt,
            hostsFile.addHostKey("somewhere-else.example.com", aKey)._hostSalt)


    def test_verifyValidKey(self):
        """
        Verifying a valid key should return a L{Deferred} which fires with
        True.
        """
        hostsFile = self.loadSampleHostsFile()
        hostsFile.addHostKey("1.2.3.4", Key.fromString(sampleKey))
        ui = FakeUI()
        d = hostsFile.verifyHostKey(ui, "www.twistedmatrix.com", "1.2.3.4",
                                    Key.fromString(sampleKey))
        l = []
        d.addCallback(l.append)
        self.assertEqual(l, [True])


    def test_verifyInvalidKey(self):
        """
        Verfying an invalid key should return a L{Deferred} which fires with a
        L{HostKeyChanged} failure.
        """
        hostsFile = self.loadSampleHostsFile()
        wrongKey = Key.fromString(thirdSampleKey)
        ui = FakeUI()
        hostsFile.addHostKey("1.2.3.4", Key.fromString(sampleKey))
        d = hostsFile.verifyHostKey(
            ui, "www.twistedmatrix.com", "1.2.3.4", wrongKey)
        return self.assertFailure(d, HostKeyChanged)


    def verifyNonPresentKey(self):
        """
        Set up a test to verify a key that isn't present.  Return a 3-tuple of
        the UI, a list set up to collect the result of the verifyHostKey call,
        and the sample L{KnownHostsFile} being used.

        This utility method avoids returning a L{Deferred}, and records results
        in the returned list instead, because the events which get generated
        here are pre-recorded in the 'ui' object.  If the L{Deferred} in
        question does not fire, the it will fail quickly with an empty list.
        """
        hostsFile = self.loadSampleHostsFile()
        absentKey = Key.fromString(thirdSampleKey)
        ui = FakeUI()
        l = []
        d = hostsFile.verifyHostKey(
            ui, "sample-host.example.com", "4.3.2.1", absentKey)
        d.addBoth(l.append)
        self.assertEqual([], l)
        self.assertEqual(
            ui.promptText,
            "The authenticity of host 'sample-host.example.com (4.3.2.1)' "
            "can't be established.\n"
            "RSA key fingerprint is "
            "89:4e:cc:8c:57:83:96:48:ef:63:ad:ee:99:00:4c:8f.\n"
            "Are you sure you want to continue connecting (yes/no)? ")
        return ui, l, hostsFile


    def test_verifyNonPresentKey_Yes(self):
        """
        Verifying a key where neither the hostname nor the IP are present
        should result in the UI being prompted with a message explaining as
        much.  If the UI says yes, the Deferred should fire with True.
        """
        ui, l, knownHostsFile = self.verifyNonPresentKey()
        ui.promptDeferred.callback(True)
        self.assertEqual([True], l)
        reloaded = KnownHostsFile.fromPath(knownHostsFile._savePath)
        self.assertEqual(
            True,
            reloaded.hasHostKey("4.3.2.1", Key.fromString(thirdSampleKey)))
        self.assertEqual(
            True,
            reloaded.hasHostKey("sample-host.example.com",
                                Key.fromString(thirdSampleKey)))


    def test_verifyNonPresentKey_No(self):
        """
        Verifying a key where neither the hostname nor the IP are present
        should result in the UI being prompted with a message explaining as
        much.  If the UI says no, the Deferred should fail with
        UserRejectedKey.
        """
        ui, l, knownHostsFile = self.verifyNonPresentKey()
        ui.promptDeferred.callback(False)
        l[0].trap(UserRejectedKey)


    def test_verifyHostIPMismatch(self):
        """
        Verifying a key where the host is present (and correct), but the IP is
        present and different, should result the deferred firing in a
        HostKeyChanged failure.
        """
        hostsFile = self.loadSampleHostsFile()
        wrongKey = Key.fromString(thirdSampleKey)
        ui = FakeUI()
        d = hostsFile.verifyHostKey(
            ui, "www.twistedmatrix.com", "4.3.2.1", wrongKey)
        return self.assertFailure(d, HostKeyChanged)


    def test_verifyKeyForHostAndIP(self):
        """
        Verifying a key where the hostname is present but the IP is not should
        result in the key being added for the IP and the user being warned
        about the change.
        """
        ui = FakeUI()
        hostsFile = self.loadSampleHostsFile()
        expectedKey = Key.fromString(sampleKey)
        hostsFile.verifyHostKey(
            ui, "www.twistedmatrix.com", "5.4.3.2", expectedKey)
        self.assertEqual(
            True, KnownHostsFile.fromPath(hostsFile._savePath).hasHostKey(
                "5.4.3.2", expectedKey))
        self.assertEqual(
            ["Warning: Permanently added the RSA host key for IP address "
             "'5.4.3.2' to the list of known hosts."],
            ui.userWarnings)


class FakeFile(object):
    """
    A fake file-like object that acts enough like a file for
    L{ConsoleUI.prompt}.
    """

    def __init__(self):
        self.inlines = []
        self.outchunks = []
        self.closed = False


    def readline(self):
        """
        Return a line from the 'inlines' list.
        """
        return self.inlines.pop(0)


    def write(self, chunk):
        """
        Append the given item to the 'outchunks' list.
        """
        if self.closed:
            raise IOError("the file was closed")
        self.outchunks.append(chunk)


    def close(self):
        """
        Set the 'closed' flag to True, explicitly marking that it has been
        closed.
        """
        self.closed = True



class ConsoleUITests(TestCase):
    """
    Test cases for L{ConsoleUI}.
    """

    def setUp(self):
        """
        Create a L{ConsoleUI} pointed at a L{FakeFile}.
        """
        self.fakeFile = FakeFile()
        self.ui = ConsoleUI(self.openFile)


    def openFile(self):
        """
        Return the current fake file.
        """
        return self.fakeFile


    def newFile(self, lines):
        """
        Create a new fake file (the next file that self.ui will open) with the
        given list of lines to be returned from readline().
        """
        self.fakeFile = FakeFile()
        self.fakeFile.inlines = lines


    def test_promptYes(self):
        """
        L{ConsoleUI.prompt} writes a message to the console, then reads a line.
        If that line is 'yes', then it returns a L{Deferred} that fires with
        True.
        """
        for okYes in ['yes', 'Yes', 'yes\n']:
            self.newFile([okYes])
            l = []
            self.ui.prompt("Hello, world!").addCallback(l.append)
            self.assertEqual(["Hello, world!"], self.fakeFile.outchunks)
            self.assertEqual([True], l)
            self.assertEqual(True, self.fakeFile.closed)


    def test_promptNo(self):
        """
        L{ConsoleUI.prompt} writes a message to the console, then reads a line.
        If that line is 'no', then it returns a L{Deferred} that fires with
        False.
        """
        for okNo in ['no', 'No', 'no\n']:
            self.newFile([okNo])
            l = []
            self.ui.prompt("Goodbye, world!").addCallback(l.append)
            self.assertEqual(["Goodbye, world!"], self.fakeFile.outchunks)
            self.assertEqual([False], l)
            self.assertEqual(True, self.fakeFile.closed)


    def test_promptRepeatedly(self):
        """
        L{ConsoleUI.prompt} writes a message to the console, then reads a line.
        If that line is neither 'yes' nor 'no', then it says "Please enter
        'yes' or 'no'" until it gets a 'yes' or a 'no', at which point it
        returns a Deferred that answers either True or False.
        """
        self.newFile(['what', 'uh', 'okay', 'yes'])
        l = []
        self.ui.prompt("Please say something useful.").addCallback(l.append)
        self.assertEqual([True], l)
        self.assertEqual(self.fakeFile.outchunks,
                         ["Please say something useful."] +
                         ["Please type 'yes' or 'no': "] * 3)
        self.assertEqual(True, self.fakeFile.closed)
        self.newFile(['blah', 'stuff', 'feh', 'no'])
        l = []
        self.ui.prompt("Please say something negative.").addCallback(l.append)
        self.assertEqual([False], l)
        self.assertEqual(self.fakeFile.outchunks,
                         ["Please say something negative."] +
                         ["Please type 'yes' or 'no': "] * 3)
        self.assertEqual(True, self.fakeFile.closed)


    def test_promptOpenFailed(self):
        """
        If the C{opener} passed to L{ConsoleUI} raises an exception, that
        exception will fail the L{Deferred} returned from L{ConsoleUI.prompt}.
        """
        def raiseIt():
            raise IOError()
        ui = ConsoleUI(raiseIt)
        d = ui.prompt("This is a test.")
        return self.assertFailure(d, IOError)


    def test_warn(self):
        """
        L{ConsoleUI.warn} should output a message to the console object.
        """
        self.ui.warn("Test message.")
        self.assertEqual(["Test message."], self.fakeFile.outchunks)
        self.assertEqual(True, self.fakeFile.closed)


    def test_warnOpenFailed(self):
        """
        L{ConsoleUI.warn} should log a traceback if the output can't be opened.
        """
        def raiseIt():
            1 / 0
        ui = ConsoleUI(raiseIt)
        ui.warn("This message never makes it.")
        self.assertEqual(len(self.flushLoggedErrors(ZeroDivisionError)), 1)



class FakeUI(object):
    """
    A fake UI object, adhering to the interface expected by
    L{KnownHostsFile.verifyHostKey}

    @ivar userWarnings: inputs provided to 'warn'.

    @ivar promptDeferred: last result returned from 'prompt'.

    @ivar promptText: the last input provided to 'prompt'.
    """

    def __init__(self):
        self.userWarnings = []
        self.promptDeferred = None
        self.promptText = None


    def prompt(self, text):
        """
        Issue the user an interactive prompt, which they can accept or deny.
        """
        self.promptText = text
        self.promptDeferred = Deferred()
        return self.promptDeferred


    def warn(self, text):
        """
        Issue a non-interactive warning to the user.
        """
        self.userWarnings.append(text)



class FakeObject(object):
    """
    A fake object that can have some attributes.  Used to fake
    L{SSHClientTransport} and L{SSHClientFactory}.
    """


class DefaultAPITests(TestCase):
    """
    The API in L{twisted.conch.client.default.verifyHostKey} is the integration
    point between the code in the rest of conch and L{KnownHostsFile}.
    """

    def patchedOpen(self, fname, mode):
        """
        The patched version of 'open'; this returns a L{FakeFile} that the
        instantiated L{ConsoleUI} can use.
        """
        self.assertEqual(fname, "/dev/tty")
        self.assertEqual(mode, "r+b")
        return self.fakeFile


    def setUp(self):
        """
        Patch 'open' in verifyHostKey.
        """
        self.fakeFile = FakeFile()
        self.patch(default, "_open", self.patchedOpen)
        self.hostsOption = self.mktemp()
        knownHostsFile = KnownHostsFile(FilePath(self.hostsOption))
        knownHostsFile.addHostKey("exists.example.com", Key.fromString(sampleKey))
        knownHostsFile.addHostKey("4.3.2.1", Key.fromString(sampleKey))
        knownHostsFile.save()
        self.fakeTransport = FakeObject()
        self.fakeTransport.factory = FakeObject()
        self.options = self.fakeTransport.factory.options = {
            'host': "exists.example.com",
            'known-hosts': self.hostsOption
            }


    def test_verifyOKKey(self):
        """
        L{default.verifyHostKey} should return a L{Deferred} which fires with
        C{1} when passed a host, IP, and key which already match the
        known_hosts file it is supposed to check.
        """
        l = []
        default.verifyHostKey(self.fakeTransport, "4.3.2.1", sampleKey,
                              "I don't care.").addCallback(l.append)
        self.assertEqual([1], l)


    def replaceHome(self, tempHome):
        """
        Replace the HOME environment variable until the end of the current
        test, with the given new home-directory, so that L{os.path.expanduser}
        will yield controllable, predictable results.

        @param tempHome: the pathname to replace the HOME variable with.

        @type tempHome: L{str}
        """
        oldHome = os.environ.get('HOME')
        def cleanupHome():
            if oldHome is None:
                del os.environ['HOME']
            else:
                os.environ['HOME'] = oldHome
        self.addCleanup(cleanupHome)
        os.environ['HOME'] = tempHome


    def test_noKnownHostsOption(self):
        """
        L{default.verifyHostKey} should find your known_hosts file in
        ~/.ssh/known_hosts if you don't specify one explicitly on the command
        line.
        """
        l = []
        tmpdir = self.mktemp()
        oldHostsOption = self.hostsOption
        hostsNonOption = FilePath(tmpdir).child(".ssh").child("known_hosts")
        hostsNonOption.parent().makedirs()
        FilePath(oldHostsOption).moveTo(hostsNonOption)
        self.replaceHome(tmpdir)
        self.options['known-hosts'] = None
        default.verifyHostKey(self.fakeTransport, "4.3.2.1", sampleKey,
                              "I don't care.").addCallback(l.append)
        self.assertEqual([1], l)


    def test_verifyHostButNotIP(self):
        """
        L{default.verifyHostKey} should return a L{Deferred} which fires with
        C{1} when passed a host which matches with an IP is not present in its
        known_hosts file, and should also warn the user that it has added the
        IP address.
        """
        l = []
        default.verifyHostKey(self.fakeTransport, "8.7.6.5", sampleKey,
                              "Fingerprint not required.").addCallback(l.append)
        self.assertEqual(
            ["Warning: Permanently added the RSA host key for IP address "
            "'8.7.6.5' to the list of known hosts."],
            self.fakeFile.outchunks)
        self.assertEqual([1], l)
        knownHostsFile = KnownHostsFile.fromPath(FilePath(self.hostsOption))
        self.assertEqual(True, knownHostsFile.hasHostKey("8.7.6.5",
                                             Key.fromString(sampleKey)))


    def test_verifyQuestion(self):
        """
        L{default.verifyHostKey} should return a L{Default} which fires with
        C{0} when passed a unknown host that the user refuses to acknowledge.
        """
        self.fakeTransport.factory.options['host'] = 'fake.example.com'
        self.fakeFile.inlines.append("no")
        d = default.verifyHostKey(
            self.fakeTransport, "9.8.7.6", otherSampleKey, "No fingerprint!")
        self.assertEqual(
            ["The authenticity of host 'fake.example.com (9.8.7.6)' "
             "can't be established.\n"
             "RSA key fingerprint is "
             "57:a1:c2:a1:07:a0:2b:f4:ce:b5:e5:b7:ae:cc:e1:99.\n"
              "Are you sure you want to continue connecting (yes/no)? "],
             self.fakeFile.outchunks)
        return self.assertFailure(d, UserRejectedKey)


    def test_verifyBadKey(self):
        """
        L{default.verifyHostKey} should return a L{Deferred} which fails with
        L{HostKeyChanged} if the host key is incorrect.
        """
        d = default.verifyHostKey(
            self.fakeTransport, "4.3.2.1", otherSampleKey,
            "Again, not required.")
        return self.assertFailure(d, HostKeyChanged)
