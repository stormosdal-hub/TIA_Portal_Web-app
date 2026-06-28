import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { execSync } from "child_process";
import { existsSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, resolve } from "path";

// Resolve vault from server.js location (.mcp/ sits inside project root)
const __dirname = dirname(fileURLToPath(import.meta.url));
const VAULT = resolve(__dirname, "..");
const GRAPHIFY = process.env.GRAPHIFY_BIN || "graphify";

const server = new Server(
  { name: "graphify", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "graphify_query",
      description: "Query the project knowledge graph with BFS traversal. Use for any question about code, concepts, files, or topics in this project.",
      inputSchema: {
        type: "object",
        properties: {
          question: { type: "string", description: "The question or topic to search for in the knowledge graph" },
        },
        required: ["question"],
      },
    },
    {
      name: "graphify_path",
      description: "Find the shortest connection path between two nodes in the knowledge graph.",
      inputSchema: {
        type: "object",
        properties: {
          from: { type: "string", description: "Starting node name" },
          to:   { type: "string", description: "Destination node name" },
        },
        required: ["from", "to"],
      },
    },
    {
      name: "graphify_explain",
      description: "Get a plain-language explanation of a specific node and its neighbors in the knowledge graph.",
      inputSchema: {
        type: "object",
        properties: {
          concept: { type: "string", description: "The concept, entity, or topic to explain" },
        },
        required: ["concept"],
      },
    },
    {
      name: "graphify_update",
      description: "Rebuild the knowledge graph after files have been added or changed. Run after creating or editing source files.",
      inputSchema: { type: "object", properties: {} },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (!existsSync(`${VAULT}/graphify-out/graph.json`) && name !== "graphify_update") {
    return {
      content: [{ type: "text", text: `No graph found at ${VAULT}/graphify-out/graph.json. Call graphify_update first to build the graph.` }],
      isError: true,
    };
  }

  try {
    let cmd;
    if (name === "graphify_query") {
      cmd = `${GRAPHIFY} query "${args.question.replace(/"/g, '\\"')}"`;
    } else if (name === "graphify_path") {
      cmd = `${GRAPHIFY} path "${args.from.replace(/"/g, '\\"')}" "${args.to.replace(/"/g, '\\"')}"`;
    } else if (name === "graphify_explain") {
      cmd = `${GRAPHIFY} explain "${args.concept.replace(/"/g, '\\"')}"`;
    } else if (name === "graphify_update") {
      cmd = `${GRAPHIFY} update .`;
    } else {
      throw new Error(`Unknown tool: ${name}`);
    }

    const output = execSync(cmd, { cwd: VAULT, timeout: 30000 }).toString();
    return { content: [{ type: "text", text: output }] };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${err.message}` }],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
