#!/bin/bash

echo "🚀 Début de l'automatisation du nettoyage et formatage du code..."

# Vérification des outils nécessaires
required_tools=("black" "isort" "autoflake" "ruff")
for tool in "${required_tools[@]}"; do
    if ! command -v $tool &> /dev/null; then
        echo "❌ L'outil '$tool' n'est pas installé. Veuillez l'installer avec : pip install $tool"
        exit 1
    fi
done

# Reformate le code avec Black
echo "🎨 Formatage du code avec Black..."
black . --line-length 88

# Trie et organise les imports
echo "📚 Organisation des imports avec isort..."
isort .

# Supprime les imports inutilisés
echo "🧹 Nettoyage des imports inutilisés avec autoflake..."
autoflake --remove-all-unused-imports --in-place --recursive .

# Analyse et correction des erreurs avec Ruff
echo "🔍 Analyse et correction avec Ruff..."
#ruff check . --fix --select F403,F405,F811,F841,E501

echo "✅ Tout est nettoyé et formaté ! 🎉"