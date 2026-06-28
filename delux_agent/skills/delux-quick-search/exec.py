import subprocess
import json
import sys

def search(query):
    try:
        # -n 5: Limitar a 5 resultados para ahorrar tokens
        # --json: Para parseo preciso
        cmd = ["ddgr", "--json", "-n", "5", query]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if not result.stdout.strip():
            return "No results found."

        data = json.loads(result.stdout)
        
        output = [f"### Web Search Results for: '{query}'\n"]
        for i, item in enumerate(data, 1):
            title = item.get("title", "No Title")
            url = item.get("url", "#")
            abstract = item.get("abstract", "No description available.")
            
            output.append(f"{i}. **{title}**")
            output.append(f"   URL: {url}")
            output.append(f"   Snippet: {abstract}\n")
            
        return "\n".join(output)

    except subprocess.CalledProcessError as e:
        return f"Error executing ddgr: {e.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: delux-quick-search <query>")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    print(search(query))
