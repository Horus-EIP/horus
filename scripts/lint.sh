#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MAS_DIR="$REPO_ROOT/src/services/mas"

echo "🧹 Démarrage du nettoyage automatique..."

cd "$MAS_DIR" || exit 1

# Nettoyage cache Python
echo "🐍 Nettoyage des fichiers cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
find . -type f -name "*.pyd" -delete 2>/dev/null
find . -type f -name ".coverage" -delete 2>/dev/null
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null
find . -type d -name "*.egg" -exec rm -rf {} + 2>/dev/null
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null
find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null
find . -type d -name ".tox" -exec rm -rf {} + 2>/dev/null

echo "✅ Cache Python nettoyée avec succès !"

# Nettoyage des anciens logs (garde les logs des 30 derniers jours)
if [ -d "logs" ]; then
    echo "📁 Nettoyage des anciens logs..."

    # Supprimer les logs de plus de 30 jours
    find logs -name "mas_*.log" -type f -mtime +30 -delete 2>/dev/null
    find logs -name "mas_errors_*.log" -type f -mtime +30 -delete 2>/dev/null

    # Compresser les logs de plus de 7 jours
    find logs -name "mas_*.log" -type f -mtime +7 ! -name "*.gz" -exec gzip {} \; 2>/dev/null
    find logs -name "mas_errors_*.log" -type f -mtime +7 ! -name "*.gz" -exec gzip {} \; 2>/dev/null

    # Afficher l'espace utilisé par les logs
    if command -v du &> /dev/null; then
        LOG_SIZE=$(du -sh logs/ 2>/dev/null | cut -f1)
        echo "📊 Taille actuelle du dossier logs: $LOG_SIZE"
    fi

    echo "✅ Nettoyage des logs terminé !"
else
    echo "ℹ️  Aucun dossier logs trouvé"
fi

# Formatage optionnel du code si les outils sont disponibles
if command -v black &> /dev/null && command -v isort &> /dev/null; then
    echo "🎨 Formatage du code avec Black et isort..."
    black . --line-length 88 --quiet
    isort . --quiet
    echo "✅ Code formaté avec succès !"
else
    echo "ℹ️  Outils de formatage non disponibles (black, isort). Pour les installer: pip install black isort"
fi

echo "🎉 Nettoyage automatique terminé avec succès !"
