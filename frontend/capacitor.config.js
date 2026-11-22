const serverUrl = process.env.CAPACITOR_SERVER_URL;

/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: "com.nova.agent",
  appName: "NOVA",
  webDir: "capacitor-web",
  ...(serverUrl
    ? {
        server: {
          url: serverUrl,
          cleartext: serverUrl.startsWith("http://"),
        },
      }
    : {}),
};

module.exports = config;