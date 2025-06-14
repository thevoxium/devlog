from flask import Flask, render_template, request, jsonify
import requests
import os
from groq import Groq
import base64

app = Flask(__name__)

# Initialize Groq client
groq_client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
)

def parse_github_url(github_url):
    """Extract owner and repo from GitHub URL"""
    if github_url.startswith('https://github.com/'):
        parts = github_url.replace('https://github.com/', '').split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None

def get_commits(owner, repo):
    """Fetch commits from main branch"""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    params = {'sha': 'main', 'per_page': 50}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        commits = response.json()
        
        commit_list = []
        for commit in commits:
            commit_list.append({
                'sha': commit['sha'],
                'message': commit['commit']['message'],
                'date': commit['commit']['author']['date'],
                'author': commit['commit']['author']['name']
            })
        return commit_list
    except requests.exceptions.RequestException as e:
        return None

def get_commit_diff(owner, repo, base_sha, head_sha):
    """Get the diff between two commits"""
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        changes = []
        for file in data.get('files', []):
            if 'patch' in file:
                changes.append({
                    'filename': file['filename'],
                    'status': file['status'],
                    'additions': file['additions'],
                    'deletions': file['deletions'],
                    'patch': file['patch']
                })
        
        return changes
    except requests.exceptions.RequestException as e:
        return None

def generate_summary(changes):
    """Generate summary using Groq API"""
    if not changes:
        return "No changes found between the selected commits."
    
    # Prepare the diff content for the LLM
    diff_content = ""
    for change in changes:
        diff_content += f"\nFile: {change['filename']}\n"
        diff_content += f"Status: {change['status']}\n"
        diff_content += f"Additions: {change['additions']}, Deletions: {change['deletions']}\n"
        # Limit patch size to avoid token limits
        patch = change['patch'][:2000] if len(change['patch']) > 2000 else change['patch']
        diff_content += f"Changes:\n{patch}\n"
        diff_content += "---\n"
    
    prompt = f"""
    Please analyze the following code changes and provide a main features added or bug solved. keep the summary very short just to 2-4 sentences at max.  
    Focus on the main features added, bugs fixed, or improvements made. Be concise but informative. No need to mention file names, just tell about the features added and potential bugs solved.
    Answer like this: "added this, added this thing too, solved this"
    Answer in lowercase, no markdown, only text.
    Code changes:
    {diff_content}
    """
    
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.3-70b-versatile",
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error generating summary: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_commits', methods=['POST'])
def get_commits_route():
    data = request.get_json()
    github_url = data.get('github_url')
    
    owner, repo = parse_github_url(github_url)
    if not owner or not repo:
        return jsonify({'error': 'Invalid GitHub URL'}), 400
    
    commits = get_commits(owner, repo)
    if commits is None:
        return jsonify({'error': 'Failed to fetch commits. Make sure the repository exists and is public.'}), 400
    
    return jsonify({'commits': commits})

@app.route('/generate_devlog', methods=['POST'])
def generate_devlog():
    data = request.get_json()
    github_url = data.get('github_url')
    base_commit = data.get('base_commit')
    head_commit = data.get('head_commit')
    
    owner, repo = parse_github_url(github_url)
    if not owner or not repo:
        return jsonify({'error': 'Invalid GitHub URL'}), 400
    
    if not base_commit or not head_commit:
        return jsonify({'error': 'Please select both commits'}), 400
    
    if base_commit == head_commit:
        return jsonify({'error': 'Please select different commits'}), 400
    
    # Get the diff between commits
    changes = get_commit_diff(owner, repo, base_commit, head_commit)
    if changes is None:
        return jsonify({'error': 'Failed to get commit differences'}), 400
    
    # Generate summary
    summary = generate_summary(changes)
    
    return jsonify({
        'summary': summary,
        'changes_count': len(changes)
    })

if __name__ == '__main__':
    app.run(debug=True)
