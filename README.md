# Hebdo Aero

Revue hebdomadaire de l'aviation commerciale, entièrement automatisée.

Chaque dimanche matin, GitHub Actions :

1. lit les flux RSS des médias aéronautiques de la semaine ;
2. fait rédiger le numéro par Claude (3 sujets à la une, une douzaine de brèves, le chiffre de la semaine), qui peut compléter par quelques recherches web ;
3. contrôle le résultat : tout sujet dont la source n'a pas été réellement lue est écarté, tout résumé qui recopie un article aussi ;
4. écrit le script d'une vidéo verticale d'environ 80 secondes, la fait lire par une voix Google et la monte : plans filmés d'avions et d'aéroports, titres animés, sous-titres mot à mot, musique et transitions ;
5. met le site à jour sur GitHub Pages ;
6. publie la vidéo en Short YouTube, en Reel Instagram et Facebook, et sur Threads.

Le dépôt contient déjà le numéro 1 (semaine du 5 au 11 octobre 2026) et son script vidéo.

## Logo et identité

Les fichiers sont dans `assets/logo/` :

| Fichier | Usage |
|---|---|
| `embleme.svg` | l'écusson seul (pied de page, vidéos) |
| `logo-sombre.svg`, `logo-clair.svg` | écusson et nom, sur fond foncé ou clair |
| `favicon.svg` | icône de l'onglet du navigateur |
| `avatar-1024.png` | photo de profil pour YouTube, Instagram, Facebook et Threads |
| `banniere-youtube.png` | bannière de la chaîne YouTube (2560 × 1440) |

Couleurs : nuit `#0B1A2E`, orange des enregistreurs de vol `#FF6A1F`, soleil `#FFB627`, ciel `#3FA9F5`.
Pour changer une couleur ou le texte du logo, modifiez le haut de `outils/logo.py` puis lancez `python outils/logo.py`.

---

## Mise en route

Comptez une heure à une heure et demie, surtout pour les comptes développeur Google et Meta. Tout se fait une seule fois. Le site fonctionne dès l'étape 2 ; chaque réseau social s'active simplement en ajoutant ses secrets, dans l'ordre que vous voulez.

### 1. Créer le dépôt GitHub

1. Créez un dépôt **public** sur GitHub (GitHub Pages est gratuit pour les dépôts publics), par exemple `hebdo-aero`.
2. Envoyez-y le contenu de ce dossier (glisser-déposer dans l'interface web, ou `git push`).
3. **Settings → Pages → Build and deployment → Source : GitHub Actions.**

Le site est publié automatiquement à l'adresse `https://VOTRE-NOM.github.io/hebdo-aero/` dès le premier envoi.

### 2. Clé Claude (obligatoire)

1. Créez une clé sur [platform.claude.com](https://platform.claude.com) (rubrique API keys) et ajoutez un moyen de paiement. Conseil : fixez une limite de dépense mensuelle, 10 $ suffisent largement.
2. Dans GitHub : **Settings → Secrets and variables → Actions → New repository secret**, nom `ANTHROPIC_API_KEY`.

À partir de là, un nouveau numéro paraît chaque dimanche sur le site.

### 3. Google : voix de synthèse et YouTube

Un seul projet Google Cloud sert pour les deux.

1. Sur [console.cloud.google.com](https://console.cloud.google.com), créez un projet et activez la facturation (obligatoire même pour rester dans la gratuité).
2. **APIs et services → Bibliothèque** : activez **Cloud Text-to-Speech API** et **YouTube Data API v3**.

**Voix (secret `GOOGLE_TTS_API_KEY`)**
3. **Identifiants → Créer des identifiants → Clé API**. Restreignez-la à « Cloud Text-to-Speech API ». Copiez-la dans le secret `GOOGLE_TTS_API_KEY`.

Sans ce secret, le site fonctionne mais aucune vidéo n'est produite.

**YouTube (secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`)**
4. **Écran de consentement OAuth** : type « Externe », ajoutez le champ d'application `.../auth/youtube.upload`, puis cliquez sur **Publier l'application** (statut « En production »). C'est indispensable : en mode « Test », le jeton expire au bout de 7 jours. L'avertissement « application non validée » qui s'affichera est normal pour un usage personnel.
5. **Identifiants → Créer des identifiants → ID client OAuth → Application de bureau.** Notez l'ID client et le code secret.
6. Sur votre ordinateur, dans ce dossier :
   ```
   python outils/youtube_jeton.py VOTRE_CLIENT_ID VOTRE_CODE_SECRET
   ```
   Connectez-vous avec le compte propriétaire de la chaîne et acceptez. Le jeton s'affiche dans le terminal.
7. Créez les trois secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` et `YOUTUBE_REFRESH_TOKEN`.

### 3 bis. Images filmées et photos (Pexels, gratuit, conseillé)

1. Créez un compte sur [pexels.com](https://www.pexels.com), puis demandez une clé sur [pexels.com/api](https://www.pexels.com/api/) (immédiat et gratuit).
2. Créez le secret `PEXELS_API_KEY`.

Chaque semaine, Claude choisit des mots-clés génériques pour chaque scène (« airport terminal night », « cargo airplane loading »…) ; le programme récupère un plan vidéo vertical pour la vidéo et des photos pour le site. Les auteurs sont crédités à l'écran, dans les descriptions et sur le site, comme Pexels le demande. Sans clé, la vidéo et le site utilisent un ciel de coucher de soleil généré par le programme.

### 4. Instagram et Facebook

Prérequis : une Page Facebook, et un compte Instagram **professionnel** (Créateur ou Entreprise) relié à cette Page.

1. Sur [developers.facebook.com](https://developers.facebook.com), créez une application de type **Entreprise**, avec les cas d'usage de gestion de Page et de publication Instagram (API Instagram avec connexion Facebook). Restez en mode développement : en tant qu'administrateur de l'application et de la Page, vous pouvez publier sans examen de Meta.
2. Ouvrez l'**Explorateur de l'API Graph**, choisissez votre application et générez un jeton utilisateur avec les autorisations : `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`.
3. Sur votre ordinateur :
   ```
   python outils/meta_jetons.py facebook ID_APPLICATION CLE_SECRETE_APPLICATION JETON_COPIE
   ```
   Le script affiche, pour votre Page, trois valeurs : créez les secrets `FACEBOOK_PAGE_ID`, `META_PAGE_TOKEN` et `INSTAGRAM_USER_ID`. Ce jeton de Page n'expire pas.

### 5. Threads

1. Dans le tableau de bord Meta, créez une application (ou ajoutez à la précédente) le cas d'usage **Accéder à l'API Threads**, avec les autorisations `threads_basic` et `threads_content_publish`.
2. **Rôles de l'application → Ajouter des testeurs Threads** : ajoutez votre compte, puis acceptez l'invitation dans Threads (Paramètres → Compte → Autorisations des sites web).
3. Générez un jeton avec le générateur de jetons utilisateur du cas d'usage Threads, puis :
   ```
   python outils/meta_jetons.py threads CLE_SECRETE_APP_THREADS JETON_COPIE
   ```
   Créez le secret `THREADS_TOKEN`.

Le jeton Threads dure 60 jours ; la publication hebdomadaire le prolonge automatiquement. Si Meta en délivre un nouveau, il faut pouvoir l'enregistrer : créez un jeton GitHub à granularité fine (**Settings du compte → Developer settings → Fine-grained tokens**), limité à ce dépôt, avec l'autorisation « Secrets : lecture et écriture », et enregistrez-le dans le secret `GH_PAT_SECRETS`. Sans lui, un avertissement apparaît dans GitHub Actions le jour où il faut mettre `THREADS_TOKEN` à jour à la main.

### 6. Premier essai

Dans l'onglet **Actions** du dépôt : **Revue hebdomadaire → Run workflow**, puis choisissez :

- **« Vidéo et réseaux du dernier numéro »** : monte la vidéo du numéro 1 et la publie partout. Le meilleur test de bout en bout.
- **« Numéro de la semaine, vidéo et réseaux »** : ce qui tourne chaque dimanche. Si la semaine est déjà couverte, rien n'est rédigé, sauf en cochant « forcer ».
- **« Écouter les voix disponibles »** : enregistre la même phrase avec dix voix françaises et les publie sur la page `/voix/` de votre site. Écoutez-les, puis recopiez le nom choisi dans `config.toml` (ligne `voix =`).
- **« Republier le site seulement »** : utile après une modification.

Le résumé de chaque exécution indique, plateforme par plateforme, ce qui a été publié avec le lien. En cas d'échec, GitHub vous envoie un e-mail. Une plateforme qui échoue n'empêche pas les autres, et relancer ne crée pas de doublon.

---

## Récapitulatif des secrets

| Secret | Sert à | Obligatoire |
|---|---|---|
| `ANTHROPIC_API_KEY` | rédiger la revue et les textes | oui |
| `GOOGLE_TTS_API_KEY` | voix de la vidéo | pour la vidéo |
| `PEXELS_API_KEY` | plans filmés et photos d'illustration | conseillé |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | YouTube | pour YouTube |
| `META_PAGE_TOKEN`, `FACEBOOK_PAGE_ID` | Facebook | pour Facebook |
| `META_PAGE_TOKEN`, `INSTAGRAM_USER_ID` | Instagram | pour Instagram |
| `THREADS_TOKEN` | Threads | pour Threads |
| `GH_PAT_SECRETS` | renouveler le jeton Threads | conseillé |

## Coûts

| Poste | Coût estimé |
|---|---|
| Claude (Sonnet 5.5, rédaction et recherches web) | environ 0,50 à 1 $ par numéro |
| Google Text-to-Speech (voix Chirp 3 HD) | gratuit : environ 5 000 caractères par mois pour 1 million offert |
| Pexels (vidéos et photos) | gratuit |
| GitHub Actions et Pages, dépôt public | gratuit |
| API YouTube, Instagram, Facebook, Threads | gratuit |

Soit quelques dollars par mois.

## Personnaliser

Tout se règle dans `config.toml` :

- **nom et sous-titre** du site, adresse e-mail de contact pour signaler une erreur, domaine personnalisé ;
- **flux RSS** lus chaque semaine : ajoutez ou retirez des blocs `[[flux]]` ;
- **modèle Claude**, nombre de recherches web et de brèves ;
- **voix** (Sulafat, chaleureuse, par défaut ; écoutez les autres avec l'action « Écouter les voix disponibles ») et vitesse de lecture ;
- **musique** : une nappe douce est générée automatiquement ; pour la remplacer, déposez un fichier libre de droits dans `assets/musique.mp3`. La musique baisse toute seule quand la voix parle ;
- **mots-clés des plans d'ouverture et de conclusion**, volume de la musique et des transitions ;
- **réseaux** : coupez une plateforme avec `false`, choisissez la visibilité YouTube, les hashtags ;
- **liens vers vos pages** (`[reseaux.profils]`) : ils s'affichent dans le pied de page et la section vidéo du site.

L'apparence du site est dans `revue/templates/style.css` (chaque rubrique a sa couleur et son pictogramme, définis dans `revue/config.py`), celle de la vidéo dans `revue/templates/video.html`.

## Tester sur votre ordinateur

```
pip install -r requirements.txt
python -m playwright install chromium        # et ffmpeg, pour la vidéo
python -m unittest discover -s tests         # tests, sans réseau
python -m revue.generer apercu               # articles de la semaine, sans appeler Claude
python -m revue.construire                   # génère le site dans _site/
python -m revue.generer video --sans-voix    # aperçu muet de la vidéo dans _medias/
```

## Bon à savoir

- **Transparence.** Le site, les vidéos et les publications indiquent que les résumés sont rédigés par une IA et lus par une voix de synthèse, et renvoient vers les articles d'origine. YouTube reçoit la mention « contenu synthétique ». Gardez ces mentions : elles sont exigées ou recommandées par les plateformes et protègent la crédibilité de la revue.
- **Droits d'auteur.** La revue reformule et cite ses sources sans reprendre leur texte. Les images viennent uniquement de Pexels (libres de droits, auteurs crédités) ou sont générées par le programme, comme la musique : aucune photo de presse.
- **Images d'illustration.** Les plans filmés montrent des avions et des aéroports génériques, pas l'événement lui-même : la mention « Image d'illustration » s'affiche à l'écran. Claude reçoit la consigne de ne jamais demander de compagnie ou de marque précise, pour éviter qu'un avion d'une autre compagnie illustre un sujet.
- **Une IA peut se tromper.** Les contrôles écartent les sources inventées et la recopie, pas toutes les erreurs d'interprétation. Un coup d'œil au numéro le dimanche matin reste une bonne habitude au début.
- **Durée des vidéos.** Elles sont calibrées sous 88 secondes, car Facebook limite à 90 secondes les Reels publiés par API.
- **Versions d'API.** Meta retire ses anciennes versions d'API au bout d'environ deux ans : pensez à mettre à jour `meta_version_api` dans `config.toml` (v25.0 aujourd'hui).
- **Vidéo sur le site.** Seule la vidéo de la semaine en cours est hébergée sur le site ; les numéros précédents renvoient vers les publications sur les réseaux.
- Deux flux, Simple Flying et Air Journal, n'ont pas pu être testés au moment de la création ; s'ils ne répondent pas, ils sont simplement ignorés.

## Organisation du dépôt

```
config.toml              réglages
data/numeros/            un fichier JSON par numéro (la source du site)
data/reseaux/            script vidéo, textes et liens des publications
revue/                   le programme (rédaction, vidéo, site, publication)
revue/templates/         gabarits du site et de la vidéo
outils/                  scripts à lancer une fois pour obtenir les jetons
.github/workflows/       la tâche du dimanche
```

Polices : Big Shoulders et Instrument Sans, sous licence SIL Open Font License (fichiers de licence dans `assets/polices/`).
