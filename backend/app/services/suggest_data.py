"""Static vocabularies behind the type-ahead suggestions.

Order matters: earlier entries are more popular and win ties. Aliases are
extra spellings a user might type ("Bangalore", "ReactJS", "full time").
Everything here is plain data; ranking lives in ``app.services.suggest``.
"""
from __future__ import annotations

# (city, state) — major Indian tech hubs first, then other cities.
INDIAN_CITIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("Bengaluru", "Karnataka", ("Bangalore",)),
    ("Hyderabad", "Telangana", ("Secunderabad",)),
    ("Pune", "Maharashtra", ()),
    ("Mumbai", "Maharashtra", ("Bombay",)),
    ("Gurugram", "Haryana", ("Gurgaon",)),
    ("Noida", "Uttar Pradesh", ()),
    ("New Delhi", "Delhi", ("Delhi",)),
    ("Delhi NCR", "Delhi", ("NCR",)),
    ("Chennai", "Tamil Nadu", ("Madras",)),
    ("Jaipur", "Rajasthan", ("Pink City",)),
    ("Ahmedabad", "Gujarat", ()),
    ("Kolkata", "West Bengal", ("Calcutta",)),
    ("Indore", "Madhya Pradesh", ()),
    ("Chandigarh", "Chandigarh", ("Tricity",)),
    ("Kochi", "Kerala", ("Cochin",)),
    ("Thiruvananthapuram", "Kerala", ("Trivandrum",)),
    ("Coimbatore", "Tamil Nadu", ()),
    ("Navi Mumbai", "Maharashtra", ()),
    ("Thane", "Maharashtra", ()),
    ("Greater Noida", "Uttar Pradesh", ()),
    ("Faridabad", "Haryana", ()),
    ("Mohali", "Punjab", ()),
    ("Panchkula", "Haryana", ()),
    ("Nagpur", "Maharashtra", ()),
    ("Nashik", "Maharashtra", ()),
    ("Aurangabad", "Maharashtra", ("Chhatrapati Sambhajinagar",)),
    ("Lucknow", "Uttar Pradesh", ()),
    ("Kanpur", "Uttar Pradesh", ()),
    ("Varanasi", "Uttar Pradesh", ("Banaras",)),
    ("Bhubaneswar", "Odisha", ()),
    ("Vadodara", "Gujarat", ("Baroda",)),
    ("Surat", "Gujarat", ()),
    ("Rajkot", "Gujarat", ()),
    ("Gandhinagar", "Gujarat", ("GIFT City",)),
    ("Mysuru", "Karnataka", ("Mysore",)),
    ("Mangaluru", "Karnataka", ("Mangalore",)),
    ("Hubballi", "Karnataka", ("Hubli",)),
    ("Visakhapatnam", "Andhra Pradesh", ("Vizag",)),
    ("Vijayawada", "Andhra Pradesh", ()),
    ("Warangal", "Telangana", ()),
    ("Madurai", "Tamil Nadu", ()),
    ("Tiruchirappalli", "Tamil Nadu", ("Trichy",)),
    ("Bhopal", "Madhya Pradesh", ()),
    ("Gwalior", "Madhya Pradesh", ()),
    ("Jabalpur", "Madhya Pradesh", ()),
    ("Jodhpur", "Rajasthan", ()),
    ("Udaipur", "Rajasthan", ()),
    ("Kota", "Rajasthan", ()),
    ("Ajmer", "Rajasthan", ()),
    ("Dehradun", "Uttarakhand", ()),
    ("Guwahati", "Assam", ()),
    ("Patna", "Bihar", ()),
    ("Ranchi", "Jharkhand", ()),
    ("Jamshedpur", "Jharkhand", ()),
    ("Raipur", "Chhattisgarh", ()),
    ("Goa", "Goa", ("Panaji", "Panjim")),
    ("Ludhiana", "Punjab", ()),
    ("Amritsar", "Punjab", ()),
    ("Jammu", "Jammu and Kashmir", ()),
    ("Srinagar", "Jammu and Kashmir", ()),
    ("Shimla", "Himachal Pradesh", ()),
    ("Puducherry", "Puducherry", ("Pondicherry",)),
    ("Kozhikode", "Kerala", ("Calicut",)),
    ("Thrissur", "Kerala", ()),
    ("Belagavi", "Karnataka", ("Belgaum",)),
    ("Agra", "Uttar Pradesh", ()),
    ("Meerut", "Uttar Pradesh", ()),
    ("Ghaziabad", "Uttar Pradesh", ()),
    ("Prayagraj", "Uttar Pradesh", ("Allahabad",)),
    ("Siliguri", "West Bengal", ()),
    ("Durgapur", "West Bengal", ()),
    ("Cuttack", "Odisha", ()),
    ("Tirupati", "Andhra Pradesh", ()),
    ("Guntur", "Andhra Pradesh", ()),
    ("Salem", "Tamil Nadu", ()),
    ("Vellore", "Tamil Nadu", ()),
    ("Hosur", "Tamil Nadu", ()),
    ("Manipal", "Karnataka", ()),
    ("Sonipat", "Haryana", ()),
    ("Bhilai", "Chhattisgarh", ()),
]

INDIAN_STATES: list[str] = [
    "Rajasthan", "Karnataka", "Maharashtra", "Telangana", "Tamil Nadu", "Delhi",
    "Haryana", "Uttar Pradesh", "Gujarat", "West Bengal", "Kerala", "Madhya Pradesh",
    "Punjab", "Andhra Pradesh", "Odisha", "Bihar", "Jharkhand", "Chhattisgarh",
    "Uttarakhand", "Himachal Pradesh", "Assam", "Goa", "Jammu and Kashmir",
    "Chandigarh", "Puducherry", "Tripura", "Meghalaya", "Manipur", "Nagaland",
    "Mizoram", "Arunachal Pradesh", "Sikkim", "Ladakh",
]

COUNTRIES: list[tuple[str, tuple[str, ...]]] = [
    ("India", ("IN", "Bharat")),
    ("United States", ("USA", "US", "America")),
    ("United Kingdom", ("UK", "Britain", "England")),
    ("Canada", ()),
    ("Germany", ()),
    ("Netherlands", ("Holland",)),
    ("United Arab Emirates", ("UAE", "Dubai")),
    ("Singapore", ()),
    ("Australia", ()),
    ("Ireland", ()),
    ("France", ()),
    ("Spain", ()),
    ("Poland", ()),
    ("Portugal", ()),
    ("Sweden", ()),
    ("Switzerland", ()),
    ("Japan", ()),
    ("Saudi Arabia", ("KSA",)),
    ("Qatar", ()),
    ("New Zealand", ()),
    ("Malaysia", ()),
    ("Israel", ()),
    ("Brazil", ()),
    ("Mexico", ()),
    ("Philippines", ()),
    ("Vietnam", ()),
    ("Indonesia", ()),
    ("Sri Lanka", ()),
    ("Bangladesh", ()),
    ("Nepal", ()),
]

# Work-mode style locations people type into location fields.
LOCATION_MODES: list[tuple[str, str, tuple[str, ...]]] = [
    ("Remote", "Work mode", ("WFH", "Work from home")),
    ("Remote - India", "Remote within India", ("Remote India",)),
    ("Hybrid", "Work mode", ()),
    ("Worldwide", "Remote, any country", ("Anywhere", "Global")),
    ("APAC", "Region", ("Asia Pacific",)),
    ("EMEA", "Region", ()),
]

# Base role titles; seniority variants are generated from these.
BASE_ROLES: list[str] = [
    "Frontend Developer", "Frontend Engineer", "React Developer", "React.js Developer",
    "React Native Developer", "Full Stack Developer", "Full Stack Engineer",
    "MERN Stack Developer", "MEAN Stack Developer", "Next.js Developer",
    "JavaScript Developer", "TypeScript Developer", "UI Developer", "UI Engineer",
    "Web Developer", "Software Engineer", "Software Developer", "Software Development Engineer",
    "Application Developer", "Product Engineer", "Angular Developer", "Vue.js Developer",
    "Node.js Developer", "Backend Developer", "Backend Engineer", "Python Developer",
    "Django Developer", "Java Developer", "Golang Developer", ".NET Developer",
    "PHP Developer", "Laravel Developer", "Ruby on Rails Developer", "Mobile Developer",
    "Android Developer", "iOS Developer", "Flutter Developer", "DevOps Engineer",
    "Site Reliability Engineer", "Cloud Engineer", "Platform Engineer", "Data Engineer",
    "Data Scientist", "Data Analyst", "Machine Learning Engineer", "AI Engineer",
    "Generative AI Engineer", "LLM Engineer", "QA Engineer", "Automation Test Engineer",
    "SDET", "Security Engineer", "Solutions Architect", "Software Architect",
    "Frontend Architect", "Technical Lead", "Engineering Manager", "UI/UX Designer",
    "Product Designer", "Design Engineer", "Product Manager", "Technical Product Manager",
    "Shopify Developer", "WordPress Developer", "Salesforce Developer", "Blockchain Developer",
    "Embedded Software Engineer", "Game Developer", "Database Administrator",
    "Business Analyst", "Scrum Master", "Technical Writer", "Developer Advocate",
]

SENIORITY_PREFIXES: list[str] = ["Senior", "Lead", "Principal", "Staff", "Junior", "Associate"]

# Words that appear in titles; used for "related title words" and keywords.
TITLE_WORDS: list[str] = [
    "react", "frontend", "front end", "ui", "ux", "javascript", "typescript", "next.js",
    "mern", "mean", "full stack", "fullstack", "web developer", "web engineer",
    "software engineer", "software developer", "sde", "node", "backend", "mobile",
    "react native", "angular", "vue", "design engineer", "product engineer", "platform",
    "web", "interface", "client side", "single page", "spa", "dashboard",
]

# Skills beyond the extraction vocabulary, so suggestions cover the common
# long tail. Canonical names only; aliases come from SKILL_VOCABULARY.
EXTRA_SKILLS: list[str] = [
    "HTML5", "CSS3", "Responsive Design", "Web Performance", "Core Web Vitals", "SEO",
    "Webpack Module Federation", "Turborepo", "Nx", "Monorepo", "ESLint", "Prettier",
    "Styled Components", "Emotion", "Chakra UI", "Ant Design", "shadcn/ui", "Radix UI",
    "Framer Motion", "Three.js", "Chart.js", "Highcharts", "Leaflet", "Mapbox",
    "Redux Saga", "Redux Thunk", "MobX", "Recoil", "Jotai", "XState", "RxJS",
    "SWR", "Axios", "tRPC", "Apollo Client", "Relay", "WebRTC", "Service Workers",
    "Progressive Web Apps", "Web Components", "Svelte", "SvelteKit", "Remix", "Astro",
    "Gatsby", "Nuxt.js", "Electron", "Tauri", "Expo", "Ionic", "Capacitor",
    "NestJS", "Koa", "Hapi", "Prisma", "TypeORM", "Sequelize", "Mongoose", "Drizzle",
    "SQL", "NoSQL", "SQLite", "DynamoDB", "Firebase", "Supabase", "Elasticsearch",
    "Kafka", "RabbitMQ", "Celery", "gRPC", "OAuth", "JWT", "Keycloak", "Auth0",
    "Microfrontends", "Serverless", "AWS Lambda", "S3", "CloudFront", "EC2",
    "Vercel", "Netlify", "Nginx", "Linux", "Bash", "GitHub Actions", "GitLab CI",
    "SonarQube", "Sentry", "Datadog", "New Relic", "Grafana", "Prometheus",
    "Storybook", "Chromatic", "Mocha", "Chai", "Enzyme", "Puppeteer", "Selenium",
    "Unit Testing", "TDD", "E2E Testing", "Accessibility (WCAG)", "Internationalization",
    "LangChain", "LlamaIndex", "Vector Databases", "pgvector", "Pinecone", "Qdrant",
    "Prompt Engineering", "Hugging Face", "TensorFlow", "PyTorch", "Pandas", "NumPy",
    "OCR", "Speech Recognition", "Data Visualization", "Design Systems", "Figma to Code",
    "Jira", "Confluence", "Scrum", "Code Review", "Mentoring", "System Design",
    "Low-Level Design", "Data Structures", "Algorithms", "Healthcare IT", "HIMS",
    "ERP", "POS Systems", "Fintech", "E-commerce", "Multi-tenant SaaS",
]

INDUSTRIES: list[str] = [
    "Software", "IT Services", "SaaS", "Healthcare", "Health Tech", "Fintech", "Banking",
    "Insurance", "E-commerce", "Retail", "EdTech", "Education", "Logistics", "Travel",
    "Hospitality", "Media", "Entertainment", "Gaming", "Telecom", "Automotive",
    "Manufacturing", "Energy", "Real Estate", "PropTech", "AgriTech", "Government",
    "Consulting", "Marketing", "AdTech", "Cybersecurity", "Artificial Intelligence",
    "Blockchain", "HR Tech", "Legal Tech", "Pharma", "Biotech", "Food Tech",
    "Non-profit", "Aerospace", "Sports",
]

COMPANY_TYPES: list[tuple[str, tuple[str, ...]]] = [
    ("product_based", ("Product-based", "Product company", "product")),
    ("startup", ("Start-up",)),
    ("mnc", ("MNC", "Multinational")),
    ("service_based", ("Service-based", "IT services", "service")),
    ("consulting", ("Consultancy",)),
    ("agency", ("Digital agency",)),
    ("enterprise", ("Large enterprise",)),
    ("unicorn", ()),
    ("government", ("PSU", "Public sector")),
    ("non-profit", ("NGO",)),
]

# Values must match what the matcher and source adapters store.
EMPLOYMENT_TYPES: list[tuple[str, str, tuple[str, ...]]] = [
    ("full_time", "Full-time", ("full time", "permanent", "fulltime", "FTE")),
    ("contract", "Contract", ("contractor", "C2H", "contract to hire", "fixed term")),
    ("part_time", "Part-time", ("part time", "parttime")),
    ("freelance", "Freelance", ("freelancer", "gig")),
    ("internship", "Internship", ("intern", "trainee")),
    ("temporary", "Temporary", ("temp", "seasonal")),
]

# Well-known product companies hiring engineers in India; user data adds more.
COMPANIES: list[str] = [
    "Atlassian", "Microsoft", "Google", "Amazon", "Adobe", "Salesforce", "Oracle",
    "Flipkart", "Swiggy", "Zomato", "Razorpay", "PhonePe", "Paytm", "CRED", "Meesho",
    "Zerodha", "Groww", "Freshworks", "Zoho", "Postman", "BrowserStack", "Chargebee",
    "InMobi", "Dream11", "Ola", "Uber", "Myntra", "Nykaa", "Urban Company", "Lenskart",
    "Practo", "Innovaccer", "HealthifyMe", "PharmEasy", "Tata 1mg", "MakeMyTrip",
    "OYO", "Delhivery", "ShareChat", "Unacademy", "upGrad", "Physics Wallah",
    "Juspay", "Slice", "Jupiter", "Fi Money", "Rapido", "BlinkIt", "Zepto",
    "Dunzo", "Cars24", "Spinny", "Licious", "Polygon", "CoinDCX", "Hasura",
    "Setu", "Sprinklr", "Druva", "Icertis", "MindTickle", "LeadSquared", "Darwinbox",
    "Keka", "Whatfix", "Hevo Data", "Rippling", "Deel", "GitLab", "Automattic",
    "Thoughtworks", "Publicis Sapient", "Infosys", "TCS", "Wipro", "HCLTech",
    "Tech Mahindra", "LTIMindtree", "Accenture", "Capgemini", "Deloitte", "EPAM",
    "Globant", "Nagarro", "Persistent Systems", "Coforge", "Mphasis",
]
