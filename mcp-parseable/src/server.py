from typing import Any
import asyncio
import httpx
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
import os

from prompts import DASHBOARD_PROMPT_TEMPLATE
from dotenv import load_dotenv
load_dotenv()

PARSEABLE_API_BASE = os.environ.get("PARSEABLE_API_BASE")
P_USERNAME = os.environ.get("P_USERNAME")
P_PASSWORD = os.environ.get("P_PASSWORD")
USER_AGENT = "mcp-parseable/1.0"

server = Server("mcp_parseable")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools.
    Each tool specifies its arguments using JSON Schema Validation
    """
    return [
        types.Tool(
            name="get-schema",
            description="Get the schema for the mentioned stream",
            inputSchema={
                "type": "object",
                "properties": {
                    "stream": {
                        "type": "string",
                        "description": "name of the stream (e.g. backend)"
                    },
                },
                "required": ["stream"]
            },
        ),
        types.Tool(
            name="post-dashboard",
            description="POST a JSON body consisting of dashboard to be created",
            inputSchema={
                "type": "object",
                "properties": {
                    "body": "object"
                },
                "required": ["body"]
            }
        )
    ]

@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="generate-dashboard-object",
            description="A prompt which describes what a dashboard is, what all it consists of, and how to make one",
            arguments=[
                types.PromptArgument(
                    name="stream_schema",
                    description="Schema of the underlying stream for which a dashboard has to be created",
                    required=True
                ),
                types.PromptArgument(
                    name="user_requirements",
                    description="A description of what all the dashboard should consist of given by the user",
                    required=True
                ),
            ]
        )
    ]

async def make_parseable_request(client: httpx.AsyncClient, url: str, body: object, requestParameter: str) -> dict[str, Any] | None:
    """
    Make a request to the Parseable server
    """
    try:
        if requestParameter=="POST":
            response = await client.post(url, json=body)
            return response

        if requestParameter=="GET":
            response = await client.get(url)
            response.raise_for_status()
            return response

    except Exception as e:
        return e

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.GetPromptResult]:
    """
    Handle tool execution requests
    """
    if not arguments:
        raise ValueError("Missing args")
    
    if name == "get-schema":
        stream = arguments.get("stream")

        if not stream:
            raise ValueError("Missing args: stream")
        
        # fetch the logstream schema
        async with httpx.AsyncClient(auth=httpx.BasicAuth("admin","admin")) as client:
            url = f"{PARSEABLE_API_BASE}/api/v1/logstream/{stream}/schema"
            response = await make_parseable_request(client, url, {}, "GET")

            if response.status_code != 200:
                return types.TextContent(type="text", text=response.text)
            
            stream_headers = response.json().get("fields", "")

            if not stream_headers:
                return [types.TextContent(type="text", text="Failed to retrieve stream headers")]
            
            # return the schema
            return [types.TextContent(type="text", text=str(stream_headers))]
        
    if name == "post-dashboard":
        request_body = arguments.get("body")
        try:
            body = eval(request_body)
        except Exception as e:
            return [types.TextContent(type="text", text=f"Failure- {str(e)}")]
        
        async with httpx.AsyncClient(auth=httpx.BasicAuth("admin","admin")) as client:
            url = f"{PARSEABLE_API_BASE}/api/v1/dashboards"
            response = await make_parseable_request(client, url, body, "POST")

            if not response:
                return [types.TextContent(type="text", text="Failed to post dashboard")]

            if response.status_code != 200:
                return types.TextContent(type="text", text=response.text)
            
            return [types.TextContent(type="text", text="Succesfully created the dashboard!")]
            
    else:
        raise ValueError(f"Unknown tool: {name}")

@server.get_prompt()
async def handle_get_prompts(
    name: str, arguments: dict | None
) -> types.GetPromptResult:
    if name == "generate-dashboard-object":
        if not arguments:
            raise ValueError("Missing arguments")
        elif "stream_schema" not in arguments:
            raise ValueError("Missing required argument: stream_schema")
        elif "user_requirements" not in arguments:
            raise ValueError("Missing required argument: user_requirements")
        
        stream_schema = arguments["stream_schema"]
        user_requirements = arguments["user_requirements"]

        prompt = DASHBOARD_PROMPT_TEMPLATE.format(stream_schema=stream_schema, user_requirements=user_requirements)

        return types.GetPromptResult(
            description="A prompt which describes what a dashboard is, what all it consists of, and how to make one",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt.strip()),
                )
            ],
        )
    
    else:
        raise ValueError(f"Unknown prompt: {name}")
        


    
async def main():
    # Run the server using stdin/stdout streams
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp_parseable",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(
                        prompts_changed=True,
                        resources_changed=True,
                        tools_changed=True
                    ),
                    experimental_capabilities={},
                ),
            ),
        )

# This is needed if you'd like to connect to a custom client
if __name__ == "__main__":
    asyncio.run(main())