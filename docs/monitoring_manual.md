# 📊 Guide de l'Infrastructure de Monitoring & Analyse - Projet Horus

Ce document détaille l'ensemble des outils d'analyse, de monitoring et d'administration déployés via Docker Compose. Il sert de référence pour la configuration, l'accès et l'utilisation de chaque service.

## 🏗️ Vue d'ensemble de l'Architecture

L'infrastructure est divisée en trois couches :
1.  **Couche de Données** : Postgres, Redis, RabbitMQ.
2.  **Couche de Collecte** : Prometheus, Postgres-Exporter.
3.  **Couche de Visualisation & Admin** : Grafana, PgAdmin, RedisInsight, Metabase.

---

## 🚀 Démarrage Rapide

Pour lancer toute la stack de monitoring :

```bash
cd src/infra
docker-compose up -d
```

> **Note Importante** : Si c'est la première fois que vous activez le monitoring SQL avancé, vous devez redémarrer complètement les conteneurs pour charger l'extension `pg_stat_statements` :
> `docker-compose down && docker-compose up -d`

---

## 1. Grafana (Tableaux de Bord Unifiés)

C'est le cockpit principal. Il centralise les métriques techniques.

*   **URL d'accès** : [http://localhost:3001](http://localhost:3001)
*   **Identifiants par défaut** : `admin` / `admin` (Skip password change au premier login).

### ⚙️ Configuration Initiale (À faire une fois)
1.  **Ajouter la Source de Données** :
    *   Allez dans `Connections` > `Data Sources` > `Add data source`.
    *   Choisissez **Prometheus**.
    *   URL : `http://prometheus:9090` (Adresse interne Docker).
    *   Cliquez sur `Save & Test`.
2.  **Importer le Dashboard PostgreSQL** :
    *   Allez dans `Dashboards` > `New` > `Import`.
    *   ID : `9628`.
    *   Sélectionnez la source Prometheus créée précédemment.

### 📈 Ce qu'on y surveille
*   **Active Connections** : Charge actuelle de la base.
*   **Transactions/sec (TPS)** : Débit de l'application.
*   **Slowest Queries** : Liste des requêtes SQL les plus lentes (nécessite `pg_stat_statements`).

---

## 2. Prometheus (Collecteur de Métriques)

Le moteur qui aspire les données toutes les 15 secondes. Il n'a pas d'interface graphique "jolie", c'est un outil de debug.

*   **URL d'accès** : [http://localhost:9090](http://localhost:9090)
*   **Fichier de config** : `src/infra/prometheus.yml`

### 🔍 Utilisation
*   Vérifier que les cibles sont "UP" : Menu `Status` > `Targets`.
*   Vous devez voir :
    *   `postgres` (UP) : Métriques de la BDD.
    *   `mas-api` (UP) : Métriques de l'application FastAPI (si le service `mas` est lancé).

---

## 3. PgAdmin 4 (Administration Base de Données)

Interface graphique complète pour gérer PostgreSQL.

*   **URL d'accès** : [http://localhost:5433](http://localhost:5433)
*   **Identifiants** : Voir `PGADMIN_DEFAULT_EMAIL` dans le fichier `.env`.

### ⚙️ Connexion au Serveur
1.  Clic droit sur `Servers` > `Register` > `Server`.
2.  Onglet **General** : Nom = `Horus DB`.
3.  Onglet **Connection** :
    *   Host name/address : `postgres` (Nom du service Docker).
    *   Port : `5432`.
    *   Maintenance database : `postgres`.
    *   Username : Voir `POSTGRES_USER` dans `.env`.
    *   Password : Voir `POSTGRES_PASSWORD` dans `.env`.

---

## 4. RedisInsight (Visualisation Cache)

Outil pour explorer le contenu du cache Redis en temps réel.

*   **URL d'accès** : [http://localhost:5540](http://localhost:5540)

### ⚙️ Connexion
1.  Cliquez sur `Add Redis Database`.
2.  Host : `redis`.
3.  Port : `6379`.
4.  Password : Voir `REDIS_PASSWORD` dans `.env`.

### 🔍 Utilisation
*   Permet de voir les clés stockées (sessions, cache API).
*   Permet de vider le cache manuellement si nécessaire.

---

## 5. RabbitMQ Management (Files d'attente)

Interface native de RabbitMQ pour surveiller les messages asynchrones.

*   **URL d'accès** : [http://localhost:15672](http://localhost:15672)
*   **Identifiants** : Voir `RABBITMQ_USER` / `RABBITMQ_PASSWORD` dans `.env`.

### 🔍 Ce qu'on y surveille
*   **Queues** : Vérifier si des messages s'empilent (signe que les consommateurs sont plantés ou trop lents).
*   **Connections** : Vérifier que les services `mas` et `agent` sont bien connectés.

---

## 6. Metabase (Business Intelligence)

Outil pour créer des graphiques "Métier" et explorer les données sans SQL.

*   **URL d'accès** : [http://localhost:5434](http://localhost:5434)

### ⚙️ Configuration Initiale
1.  Au premier lancement, cliquez sur "Let's get started".
2.  Choisissez "PostgreSQL".
3.  **Host** : `postgres`.
4.  **Database name** : Voir `POSTGRES_DB` dans `.env`.
5.  **Username/Password** : Ceux du `.env`.

### 💡 Cas d'usage
*   Créer des dashboards pour le client final (ex: "Nombre d'utilisateurs inscrits par jour", "Nombre de tâches traitées").
*   Explorer les tables de données brute facilement.

---

## 🛠️ Résolution de problèmes courants

**Problème : Grafana n'affiche aucune donnée.**
*   Vérifiez que Prometheus est UP (`http://localhost:9090/targets`).
*   Vérifiez que le conteneur `postgres-exporter` est lancé.

**Problème : "Connection refused" dans PgAdmin ou Metabase.**
*   Assurez-vous d'utiliser le nom d'hôte `postgres` et non `localhost` lorsque vous configurez la connexion *depuis* un autre conteneur Docker.

**Problème : Les "Slow Queries" sont vides.**
*   Avez-vous bien redémarré Postgres après avoir ajouté la config `pg_stat_statements` ?
*   Vérifiez en SQL : `SELECT * FROM pg_stat_statements LIMIT 5;`. Si cela renvoie une erreur, l'extension n'est pas active.
