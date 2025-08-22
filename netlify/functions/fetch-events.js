/**
 * Netlify serverless function to securely fetch sports events data from the Cloudbet API.
 * This function now fetches data for a specific list of top leagues.
 */
exports.handler = async (event, context) => {
  // Get the secret API key from the Netlify environment variables
  const API_KEY = process.env.API_KEY;

  // Check if the API key is configured in the Netlify environment
  if (!API_KEY) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'API key is not configured.' }),
    };
  }
  
  // Set up the time window for the API call (from now to 72 hours in the future)
  const from = Math.floor(Date.now() / 1000);
  const to = from + (72 * 3600); 
  
  // List of specific league keys to fetch
  const leagueKeys = [
    'soccer-france-ligue-1',
    'soccer-england-premier-league',
    'soccer-international-clubs-uefa-champions-league',
    'soccer-international-clubs-uefa-europa-league',
    'soccer-international-clubs-t6eeb-uefa-europa-conference-league',
    'soccer-germany-bundesliga',
    'soccer-italy-serie-a',
    'soccer-spain-laliga',
    'soccer-serbia-superliga'
  ];

  try {
    // Create a fetch promise for each league
    const fetchPromises = leagueKeys.map(key => {
      const API_URL = `https://sports-api.cloudbet.com/pub/v2/odds/competitions/${key}?from=${from}&to=${to}&players=true&limit=100`;
      return fetch(API_URL, {
        headers: { 'X-API-Key': API_KEY }
      });
    });

    // Execute all fetches concurrently
    const responses = await Promise.all(fetchPromises);

    const competitions = [];
    for (const response of responses) {
      if (response.ok) {
        const data = await response.json();
        // The API returns a single competition object per call.
        // We only add it if it actually has events for the given timeframe.
        if (data && data.events && data.events.length > 0) {
          competitions.push(data);
        }
      } else {
        // Log an error but don't fail the entire function, to allow for partial data
        console.error(`API Error for one of the leagues: ${response.status} ${response.statusText}`);
      }
    }

    // Return the aggregated data in the format the frontend expects
    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ competitions }),
    };

  } catch (error) {
    // Handle any unexpected errors during the fetch operation
    console.error("Function Error:", error);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: `Function Error: ${error.message}` }),
    };
  }
};
