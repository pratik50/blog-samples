<h1 align="center">
MCP-Parseable
</h1>

This repository contains the MCP-Server built for Parseable.

[Parseable MCP Blog]()

The Parseable MCP Server exposes-
### Tools
`get-schema` - Makes an API call to the parseable server to fetch the schema for the mentioned stream.

`post-dashboard` - POSTs a dashboard object to the Parseable server

### Prompts
`generate-dashboard-object` - A prompt which explains what a dashboard is (according to Parseable), what all it consists of, and an example of such an object

### Getting Started
- Create a virtual env and install the requirements
```
python -m venv venv
pip install -r requirements.txt
```
- Edit the .env file with your Parseable Query/Standalone server's URL, username, and password
- Edit Claude Desktop's config file to point it towards MCP-Parseable's `server.py` (the command should use your venv's python.exe)
```json
{
    "mcpServers": {
        "mcp_parseable": {
            "command": "YOUR:\\VENV\\Scripts\\python.exe",
            "args": [
                "YOUR:\\PATH\\mcp-parseable\\src\\server.py"
            ]
        }
    }
}
```
(To open the config file, from your Claude Desktop app,  go to `File -> Settings -> Developer -> Edit Config`)
- Run your Parseable server
- Open Claude Desktop App