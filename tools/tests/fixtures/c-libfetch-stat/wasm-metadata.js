const fs = require("node:fs");
(async () => {
  const { instance } = await WebAssembly.instantiate(fs.readFileSync(process.argv[2]), {});
  const failedLine = instance.exports.control();
  if (failedLine !== 0) throw new Error("wasm32 metadata control failed at C line " + failedLine);
  console.log("wasm32 libfetch metadata conversion controls passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
