const { neon } = require('@neondatabase/serverless');
const { drizzle } = require('drizzle-orm/neon-http');
function database(url) {
  const client = neon(url);
  const query = client.query.bind(client);
  client.query = (text, params, options = {}) => query(text, params, {
    ...options, fetchOptions: { ...options.fetchOptions, signal: AbortSignal.timeout(15000) },
  });
  return drizzle(client);
}
module.exports = { database };
