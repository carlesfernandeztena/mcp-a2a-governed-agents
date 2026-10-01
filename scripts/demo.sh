# The `demo` command with tab completion. Load it in each terminal:  source scripts/demo.sh
# Runs on the host with uv, against the services from `docker compose up -d`.
unalias demo 2>/dev/null   # an old `alias demo=…` would hijack the function below
DEMO_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

demo() { uv run --quiet --directory "$DEMO_REPO" python -m cli "$@"; }

_demo() {
  local cur="${COMP_WORDS[COMP_CWORD]}" cmd="${COMP_WORDS[1]}" n="$COMP_CWORD" words=""
  # word lists come straight from the data files, so they never drift from what the demo knows
  local people serials parts
  people=$(grep -o '"id": "[a-z]*"' "$DEMO_REPO/data/people.json" | cut -d'"' -f4)
  serials=$(tail -n +2 "$DEMO_REPO/data/instruments.csv" | cut -d, -f2)
  parts=$(tail -n +2 "$DEMO_REPO/data/parts_catalog.csv" | cut -d, -f2)
  if [ "$n" -eq 1 ]; then
    words="follow ask view approve skill registry eval promotions gateway stop start stubs who freezers"
  else
    case "$cmd" in
      ask)     [ "$n" -eq 2 ] && words="$people"   # then the question: free text in quotes (demo ask -h has examples)
               [ "${COMP_WORDS[n-1]}" = "--agent" ] && words="triage-agent quick-lookup" ;;
      approve) words="$people --reject --proposal" ;;
      skill)   case "$n:${COMP_WORDS[2]}" in
                 2:*) words="manuals context order" ;;
                 3:context|3:order) words="$serials" ;;
                 4:order) words="$parts" ;;
                 *) words="--as" ;;
               esac ;;
      eval)    words="current rc last --background" ;;
      gateway) [ "$n" -eq 2 ] && words="use restart"
               [ "${COMP_WORDS[2]}" = "use" ] && [ "$n" -eq 3 ] && words="luna sonnet haiku" ;;
      stop|start) words="scheduling-agent skill-context skill-manuals skill-parts dataproducts gateway" ;;
      view)    words="--raw" ;;
    esac
  fi
  [ "${COMP_WORDS[n-1]}" = "--as" ] && words="$people"
  COMPREPLY=($(compgen -W "$words" -- "$cur"))
}
complete -F _demo demo
echo "demo ready: type demo (Tab completes commands, people, serials, parts)"
