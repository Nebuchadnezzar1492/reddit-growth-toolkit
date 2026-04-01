# Example personas config — copy to personas.local.py and customize
# personas.local.py is gitignored and won't be pushed
PERSONAS = {
    "tech_builder": {
        "niche": [
            "selfhosted", "homelab", "docker", "linux",
            "HomeNetworking", "sysadmin",
        ],
        "builder": [
            "DIY", "3Dprinting", "HomeImprovement",
            "tools", "BuyItForLife",
        ],
        "general": [
            "AskReddit", "technology", "mildlyinfuriating",
            "unpopularopinion", "pcmasterrace", "buildapc",
            "CasualConversation", "NoStupidQuestions", "TIFU",
            "MaliciousCompliance", "Wellthatsucks", "LifeProTips",
            "todayilearned", "explainlikeimfive", "personalfinance",
            "Frugal", "gadgets", "antiwork", "Futurology",
        ],
    },
    "privacy_advocate": {
        "niche": [
            "privacy", "degoogle", "privacytoolsIO", "selfhosted",
            "GDPR", "datahoarder",
        ],
        "general": [
            "AskReddit", "technology", "mildlyinfuriating",
            "unpopularopinion", "NoStupidQuestions", "CasualConversation",
            "LifeProTips", "antiwork", "Futurology", "TIFU",
            "MaliciousCompliance", "Wellthatsucks", "todayilearned",
            "explainlikeimfive", "meirl",
        ],
    },
}
