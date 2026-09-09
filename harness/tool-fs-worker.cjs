// Executed under sandbox-exec. It receives no model/provider/session state.
const fs = require('node:fs/promises');
const constants = require('node:fs').constants;
process.on('message', async ({id, operation, path, data}) => {
  try {
    let value;
    switch (operation) {
      case 'read': value = await fs.readFile(path); break;
      case 'head': {
        const file = await fs.open(path, 'r');
        try {
          const buffer = Buffer.alloc(4100);
          const {bytesRead} = await file.read(buffer, 0, buffer.length, 0);
          value = buffer.subarray(0, bytesRead);
        } finally { await file.close(); }
        break;
      }
      case 'access': await fs.access(path, data === 'write' ? constants.R_OK | constants.W_OK : constants.R_OK); break;
      case 'mkdir': await fs.mkdir(path, {recursive:true}); break;
      case 'write': await fs.writeFile(path, data, 'utf8'); break;
      default: throw new Error('Unknown file operation');
    }
    process.send({id, value});
  } catch (error) {
    process.send({id, error:{message:error.message, code:error.code}});
  }
});
process.on('disconnect', () => process.exit(0));
