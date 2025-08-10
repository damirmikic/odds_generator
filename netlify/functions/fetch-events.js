exports.handler = async (event, context) => {
  // Get the secret API key from the Netlify environment variables
  const API_KEY = process.env.API_KEY;

  if (!API_KEY) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'API key is not configured.' }),
    };
  }
  
  // Set up the API call parameters
  const from = Math.floor(Date.now() / 1000);
  const to = from + (48 * 3600); // 48 hours from now
  const API_URL = `https://sports-api.cloudbet.com/pub/v2/odds/events?sport=soccer&from=${from}&to=${to}&live=false&markets=soccer.anytime_goalscorer&markets=soccer.match_odds&players=true&limit=1000`;
  
    console.log('Fetching API URL:', API_URL); // Log the URL for debugging
  
    try {
      const response = await fetch(API_URL, {
        headers: { 'X-API-Key': API_KEY }
      });

    if (!response.ok) {
      // Forward the API's error status and message if possible
      const errorBody = await response.text();
      return {
        statusCode: response.status,
        body: JSON.stringify({ error: `API Error: ${response.statusText}`, details: errorBody }),
      };
    }

    const data = await response.json();

    return {
      statusCode: 200,
      body: JSON.stringify(data),
    };

  } catch (error) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: `Function Error: ${error.message}` }),
    };
  }
};
