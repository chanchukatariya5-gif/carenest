from dotenv import load_dotenv

load_dotenv()
import asyncio
import json
import os

from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVER_URL = "http://127.0.0.1:8000/mcp"
MODEL = "gemini-3.8-flash"


def mcp_tools_to_gemini(mcp_tools):
    """Convert MCP tool schemas into Gemini function declarations."""
    declarations = []

    for tool in mcp_tools:
        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or tool.name,
                parameters_json_schema=tool.inputSchema,
            )
        )

    return [types.Tool(function_declarations=declarations)]


async def main():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("Missing GEMINI_API_KEY environment variable.")
        return

    ai = genai.Client(api_key=api_key)

    print("Connecting to CareNest MCP server...")

    async with streamable_http_client(SERVER_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Connected successfully!")

            tool_result = await session.list_tools()
            available_tools = tool_result.tools
            gemini_tools = mcp_tools_to_gemini(available_tools)

            print(f"Loaded {len(available_tools)} CareNest tools.")
            print("CareNest AI is ready. Type 'exit' to quit.\n")

            history = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "You are CareNest, a helpful caregiving assistant. "
                                "Use available tools when appropriate. "
                                "Ask for missing required information before "
                                "creating appointments or reminders. "
                                "Never claim a reminder sends a notification; "
                                "it only stores a reminder. "
                                "Do not invent tool results."
                            )
                        )
                    ],
                )
            ]

            while True:
                message = input("You: ").strip()

                if message.lower() in {"exit", "quit"}:
                    break

                if not message:
                    continue

                history.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=message)],
                    )
                )

                try:
                    for _ in range(5):
                        response = await asyncio.to_thread(
                            ai.models.generate_content,
                            model=MODEL,
                            contents=history,
                            config=types.GenerateContentConfig(
                                tools=gemini_tools,
                                temperature=0.2,
                            ),
                        )

                        if not response.candidates:
                            print("AI returned no response. Try again.")
                            break

                        model_content = response.candidates[0].content
                        history.append(model_content)

                        calls = response.function_calls or []

                        if not calls:
                            print(
                                "\nCareNest:",
                                response.text or "(No text response)",
                                "\n",
                            )
                            break

                        for call in calls:
                            # Only execute tools actually exposed by our MCP server.
                            if not any(
                                tool.name == call.name
                                for tool in available_tools
                            ):
                                raise ValueError(
                                    f"Unknown MCP tool requested: {call.name}"
                                )

                            arguments = dict(call.args or {})
                            print(f"Using tool: {call.name}")

                            result = await session.call_tool(
                                call.name,
                                arguments=arguments,
                            )

                            output = {
                                "is_error": result.isError,
                                "content": [
                                    {
                                        "type": item.type,
                                        "text": getattr(item, "text", ""),
                                    }
                                    for item in result.content
                                ],
                            }

                            history.append(
                                types.Content(
                                    role="user",
                                    parts=[
                                        types.Part.from_function_response(
                                            name=call.name,
                                            response={"result": output},
                                        )
                                    ],
                                )
                            )
                    else:
                        print("Stopped after 5 AI/tool rounds.")

                except Exception as exc:
                    print(f"Request failed: {exc}")

    ai.close()


if __name__ == "__main__":
    asyncio.run(main())
