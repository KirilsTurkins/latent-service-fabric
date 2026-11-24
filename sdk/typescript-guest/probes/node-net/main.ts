// Ordinary finite Socket calls only. No private import, resource id, shutdown
// callback or job pump. The owning host supplies the real read-entry barrier.
import net, {Socket} from 'node:net';
import isPortReachable from 'is-port-reachable';

function heldPausedPayload(port: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const primary = new Socket(), control = new Socket();
    let resumed = false, ended = false, closed = 0, received = '';
    const done = () => {
      if (++closed === 2) resolve('node-net:paused-payload:pass');
    };
    primary.on('error', reject);
    control.on('error', reject);
    primary.once('connect', () => {
      primary.end();
      control.connect(port, '127.0.0.1');
    });
    primary.once('end', () => {
      if (!resumed || received !== 'Q') { reject(new Error('node-net:early-eof')); return; }
      ended = true;
    });
    primary.once('close', hadError => {
      if (hadError || !ended || primary.bytesRead !== 1) {
        reject(new Error('node-net:paused-payload-close')); return;
      }
      done();
    });
    control.once('close', hadError => {
      if (hadError || !resumed) { reject(new Error('node-net:control-close-order')); return; }
      done();
    });
    control.once('data', bytes => {
      if (bytes.length !== 1 || bytes[0] !== 114 || primary.bytesRead !== 1 || ended) {
        reject(new Error('node-net:missing-paused-payload')); return;
      }
      resumed = true;
      primary.on('data', chunk => { received += chunk.toString('utf8'); });
      control.destroy();
    });
    primary.connect(port, '127.0.0.1');
  });
}

export const api = {
  run(mode: number, port: number): Promise<string> {
    if (mode === 7) return heldPausedPayload(port);
    if (mode === 5 || mode === 6)
      return isPortReachable(port, {host: '127.0.0.1'}).then(reachable => 'node-net:published:' + reachable);
    if (!Number.isInteger(mode) || mode < 0 || mode > 4)
      throw new Error('node-net:unknown-case');
    return new Promise((resolve, reject) => {
      if (mode === 0) {
        const socket = net.createConnection(port, '127.0.0.1');
        let received = '', ended = false, finished = false;
        socket.on('error', reject);
        socket.on('connect', () => socket.end('q'));
        socket.on('data', bytes => { received += bytes.toString('utf8'); });
        socket.on('end', () => { ended = true; });
        socket.on('finish', () => { finished = true; });
        socket.once('close', hadError => {
          if (hadError || received !== 'q' || !ended || !finished ||
              socket.bytesRead !== 1 || socket.bytesWritten !== 1) {
            reject(new Error('node-net:echo-or-close-order')); return;
          }
          resolve('node-net:echo:pass');
        });
        return;
      }
      if (mode === 2) {
        const socket = new Socket();
        let denied: Error | undefined;
        socket.on('error', error => { denied = error; });
        socket.once('close', hadError => {
          if (!hadError || denied === undefined ||
              (denied as Error & {code?: string}).code !== 'EACCES') {
            reject(new Error('node-net:alternate-must-be-denied')); return;
          }
          resolve('node-net:denied:EACCES');
        });
        socket.connect({host: '127.0.0.1', port});
        return;
      }
      const primary = new Socket(), control = new Socket();
      let closed = 0, permitted = false;
      const complete = () => {
        if (++closed === 2)
          resolve(mode === 1 ? 'node-net:sibling:pass' : 'node-net:destroy:pass');
      };
      primary.on('error', reject); control.on('error', reject);
      primary.on('data', () => reject(new Error('node-net:primary-read-not-held')));
      primary.once('connect', () => control.connect(port, '127.0.0.1'));
      primary.once('close', hadError => {
        if (hadError || !permitted) { reject(new Error('node-net:primary-close')); return; }
        if (mode === 3) {
          // A real peer-visible marker after ordinary primary close. It is not
          // a claim that borrow ACK alone retired an IoCall/IoTransfer.
          control.write('a', error => {
            if (error) { reject(error); return; }
            control.destroy();
          });
        }
        if (mode !== 4) complete();
      });
      control.once('close', hadError => {
        if (hadError || !permitted) { reject(new Error('node-net:control-close')); return; }
        if (mode === 4) {
          // Only primary remains unclosed. No assertion, new call or cleanup
          // occurs after this resolution: the ORIGINAL export guard must fail.
          resolve('node-net:unclosed-root-must-not-escape');
        } else complete();
      });
      control.once('data', bytes => {
        if (permitted || bytes.length !== 1 || bytes[0] !== 112) {
          reject(new Error('node-net:real-peer-permit')); return;
        }
        permitted = true;
        control.pause(); // Keep the finite protocol to one control read; OutboundRequests8 counts connects, not WIT calls.
        if (mode === 1) {
          control.destroy();
          primary.write('s', error => {
            if (error) { reject(error); return; }
            primary.destroy();
          });
        } else if (mode === 3) primary.destroy();
        else control.destroy(); // Mode4 deliberately leaves primary open.
      });
      primary.connect({host: '127.0.0.1', port});
    });
  },
};
