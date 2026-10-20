"""Standard JDK exception behavior and normal captured HTTP source boundaries."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tools import java_http_client
from tools.rust_capsule_project import ROOT

SOURCE = 'client/dev/latent/guest/client/net/SocketTimeoutException.java'


class JavaTimeoutExceptionTests(unittest.TestCase):
    def test_standard_constructors_parent_bytes_and_serial_identity_match_installed_jdk(self):
        java, javac = shutil.which('java'), shutil.which('javac')
        self.assertTrue(java and javac, 'A real JDK is required for the timeout exception control')
        probe = '''import java.io.*;
public class Probe {
  static String inspect(InterruptedIOException value) {
    if (value.bytesTransferred != 0 || value.getCause() != null) throw new AssertionError();
    value.bytesTransferred = 7;
    return String.valueOf(value.getMessage()) + ":" + value.bytesTransferred + ":"
      + value.getClass().getSuperclass().getName() + ":"
      + ObjectStreamClass.lookup(value.getClass()).getSerialVersionUID();
  }
  public static void main(String[] args) {
    String[] messages = {null, "", "phase-timeout", "read\\u0000timeout"};
    if (!inspect(new java.net.SocketTimeoutException()).equals(
        inspect(new dev.latent.guest.client.net.SocketTimeoutException()))) throw new AssertionError();
    for (String message : messages) {
      if (!inspect(new java.net.SocketTimeoutException(message)).equals(
          inspect(new dev.latent.guest.client.net.SocketTimeoutException(message)))) throw new AssertionError();
    }
    try { throw new dev.latent.guest.client.net.SocketTimeoutException("original"); }
    catch (InterruptedIOException value) {
      if (!"original".equals(value.getMessage())) throw new AssertionError();
    }
    System.out.println("STANDARD_TIMEOUT_CASES=6");
  }
}'''
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory/'Probe.java').write_text(probe, encoding='utf8')
            compiled = subprocess.run([javac, '-proc:none', '-encoding', 'UTF-8', '-d', temporary,
                str(ROOT/'sdk/java-guest'/SOURCE), str(directory/'Probe.java')],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
            result = subprocess.run([java, '-cp', temporary, 'Probe'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout.strip(), b'STANDARD_TIMEOUT_CASES=6')

    def test_timeout_uses_same_closed_standard_substitution_and_reference_normalization(self):
        root = ROOT/'sdk/java-guest/client/compiler/dev/latent/guest/client/compiler'
        source = (root/'HttpSubstitution.java').read_text()
        selected = re.search(r'API = Set\.of\(([^;]+)\);', source).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', selected),
            ['Proxy','Proxy$Type','SocketAddress','InetSocketAddress','SocketTimeoutException'])
        self.assertIn('.dontFallbackWhenNoSubstitution()', source)
        plugin = (root/'HttpPlugin.java').read_text()
        self.assertIn('HttpSubstitution.API.contains', plugin)
        self.assertIn('HttpSubstitution.STANDARD + suffix', plugin)

    def test_normal_profile_captures_the_exception_source_without_application_patch(self):
        profile = json.loads(java_http_client.profile(ROOT/'sdk/java-guest', b'recipe', b'source', b'component'))
        self.assertIn('dev/latent/guest/client/net/SocketTimeoutException.java', profile['inputs'])
        self.assertEqual(profile['profile'], java_http_client.PROFILE_ID)
        source = (ROOT/'sdk/java-guest'/SOURCE).read_text()
        self.assertIn('extends java.io.InterruptedIOException', source)
        self.assertNotIn('bytesTransferred =', source)
