# Shared interactive configuration for bash and zsh on macOS and Linux.
# Keep credentials and machine-specific initialization in local startup files.

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac


alias ls="ls -F"
alias ll="ls -lh"
alias lt="du -sh * | sort -h"


# ---- Git shortcuts ----------------------------------------------------------

unalias git-clear-branches git-clear-branches1 2>/dev/null || :

git-clear-branches() {
  git branch | grep -v "next" | grep -v "dev" | grep -v "master" | xargs git branch -D
}

git-clear-branches1() {
  git branch -d $(git branch | grep -e ".*SULF.*" -e ".*LAUn.*" -e ".*-uat.*" -i)
}

alias undo-last-commit="git reset --soft HEAD~1"
alias debug-accounts="git stash apply stash^{/debug}"

git-reset-branch() {
  local timestamp
  timestamp=$(date +%s)

  git add .
  git stash push -m "$timestamp"
  git fetch "$1" "$2"
  git reset --hard "$1/$2"
  git stash apply stash^{/"$timestamp"}
}

get-url-from-ssh() {
  local branch url url2
  branch=${2:-"uat"}
  url=$1
  url2=$(echo "https://github.com/${url:15}" | awk '{ print substr( $0, 1, length($0)-4 ) }')
  echo "${url2}/compare/${branch}...satyasaibhushan:$(git rev-parse --abbrev-ref HEAD)?expand=1"
}

open-repo-url() {
  if [ "$(uname -s)" = Darwin ]; then
    if [ -n "${browser:-}" ]; then
      open -a "$browser" "$1"
    else
      open "$1"
    fi
  elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1"
  else
    printf '%s\n' "$1"
  fi
}

git-uat() {
  local branch uatBranch
  branch=$(git rev-parse --abbrev-ref HEAD)
  uatBranch=${1:-"uat"}

  git checkout -b "$branch-uat"
  git pull origin "$branch-uat" --no-rebase --no-edit
  git pull upstream "$uatBranch" --no-rebase --no-edit
  git push origin "$branch-uat"
  open-repo-url "$(get-url-from-ssh "$(git config --get remote.upstream.url)")"
  git checkout "$branch"
  git branch -D "$branch-uat"
}

git-pr() {
  local branch
  branch=${1:-"master"}

  git pull upstream "$branch" --no-rebase --no-edit
  git push origin "$(git rev-parse --abbrev-ref HEAD)"
  open-repo-url "$(get-url-from-ssh "$(git config --get remote.upstream.url)" "$branch")"
}


# ---- Devspace shortcuts -----------------------------------------------------

alias ddep="devspace deploy --var WORKLOAD_TYPE=api"
alias dd="devspace purge --var WORKLOAD_TYPE=api && devspace deploy --var WORKLOAD_TYPE=api && devspace dev --var WORKLOAD_TYPE=api"
alias ddev="devspace dev --var WORKLOAD_TYPE=api"
alias dpurge="devspace purge --var WORKLOAD_TYPE=api"
alias env_sync="devspace run sync_env"
alias pdep="kn panels && devspace deploy --var WORKLOAD_TYPE=api TARGET_REGION=us"
alias pd="kn panels && devspace purge --var WORKLOAD_TYPE=api TARGET_REGION=us && devspace deploy --var WORKLOAD_TYPE=api TARGET_REGION=us && devspace dev --var WORKLOAD_TYPE=api TARGET_REGION=us"
alias pdev="kn panels && devspace dev --var WORKLOAD_TYPE=api TARGET_REGION=us"


# Use the shared devbox checkout when present; allow a local override.
if [ -z "${CODE_ROOT:-}" ]; then
  if [ -d /srv/Code ]; then
    CODE_ROOT=/srv/Code
  else
    CODE_ROOT="$HOME/Code"
  fi
fi
export CODE_ROOT

# Repository shortcuts

alias dui='cd "${CODE_ROOT}/frontend/dashboard"'
alias eui='cd "${CODE_ROOT}/frontend/employer-ui"'
alias panels-ui='cd "${CODE_ROOT}/frontend/panels-ui"'

alias accounts='cd "${CODE_ROOT}/backend/dashboard-api-accounts"'
alias employer-jobs='cd "${CODE_ROOT}/backend/employer-api-jobs"'
alias ejobs='cd "${CODE_ROOT}/backend/employer-api-jobs"'


# ---- Kubernetes shortcuts ---------------------------------------------------

unalias kx kn 2>/dev/null || :

kx() {
  if [[ -n "$1" ]]; then
    kubectl config use-context "$1"
  else
    kubectl config current-context
  fi
}

kn() {
  if [[ -n "$1" ]]; then
    kubectl config set-context --current --namespace "$1"
  else
    kubectl config view --minify | grep namespace | cut -d" " -f6
  fi
}



alias sso-permissions='echo "chmod -R 775"'
alias shibbo-logs="echo 'copilot svc exec -a candidate -n newrelic-fluentd-agent -e prod-us' && echo 'cd /var/efs-read/shibboleth-sp-api/shibboleth/logs'"
alias login-cache-remove="rm -r ~/.kube/cache/oidc-login"

cpp() {
  local folder file
  folder=${1:-"."}
  file=${2:-"sol.cpp"}

  if [[ ! -d "$folder" ]]; then
    echo "Folder does not exist: $folder"
    return 1
  fi

  if [[ ! -f "$folder/$file" ]]; then
    echo "File does not exist: $folder/$file"
    return 1
  fi

  g++ -std=c++17 -o "./$folder/exec" "./$folder/$file"
  "./$folder/exec"
  rm "./$folder/exec"
}

