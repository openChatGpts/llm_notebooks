from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import GPT4AllEmbeddings
from langchain.prompts import PromptTemplate
from langchain_community.chat_models import ChatOllama
from langchain_core.output_parsers import JsonOutputParser
from langchain.prompts import PromptTemplate
from langchain_community.chat_models import ChatOllama
from langchain_core.output_parsers import JsonOutputParser
from langchain import hub
from langchain_community.chat_models import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from typing_extensions import TypedDict
from typing import List
from langchain.schema import Document
from langgraph.graph import END, StateGraph
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain.schema import Document
from langchain_community.document_loaders import PyPDFLoader
import streamlit as st
import os
import pprint
local_llm = "llama3"
tavily_api_key = os.environ['TAVILY_API_KEY'] = ''
st.title("多 PDF 文件聊天机器人 - LLAMA3 & Adaptive RAG")
user_input = st.text_input("对 PDF 文件提问:", placeholder="请在输入框中输入您的提问", key='input',value="llm agent memory")

with st.sidebar:
    uploaded_files = st.file_uploader("上传 PDF 文件（可多个）", type=['pdf'], accept_multiple_files=True)
    process = st.button("导入并处理文件")

if process:
    if not uploaded_files:
        st.warning("请上传至少一份 PDF 文件。")
        st.stop()

    # Ensure the temp directory exists
    # 当前路径
    temp_dir = os.getcwd()
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    st.write("处理上传的文件.....")
    # 处理每一个上传的文件
    for uploaded_file in uploaded_files:
        temp_file_path = os.path.join(temp_dir, uploaded_file.name)
        
        # 将文件保存到磁盘
        with open(temp_file_path, "wb") as file:
            file.write(uploaded_file.getbuffer())  # Use getbuffer() for Streamlit's UploadedFile
        
        # 使用 PyPDFLoader 加载 PDF
        try:
            loader = PyPDFLoader(temp_file_path)
            data = loader.load()  # Assuming loader.load() is the correct method call
            st.write(f"加载成功，文件名 {uploaded_file.name}")
        except Exception as e:
            st.error(f"无法加载 {uploaded_file.name}: {str(e)}")

    st.write("对数据集进行分块.....")
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=250, chunk_overlap=0
    )
    text_chunks = text_splitter.split_documents(data)

    # 添加到向量数据库 vectorDB
    vectorstore = Chroma.from_documents(
        documents=text_chunks,
        collection_name="rag-chroma",
        embedding=GPT4AllEmbeddings(),
    )
    retriever = vectorstore.as_retriever()
    llm = ChatOllama(model=local_llm, format="json", temperature=0)

    prompt = PromptTemplate(
        template="""You are an expert at routing a user question to a vectorstore or web search. \n
        Use the vectorstore for questions on LLM  agents, prompt engineering, and adversarial attacks. \n
        You do not need to be stringent with the keywords in the question related to these topics. \n
        Otherwise, use web-search. Give a binary choice 'web_search' or 'vectorstore' based on the question. \n
        Return the a JSON with a single key 'datasource' and no premable or explaination. \n
        Question to route: {question}""",
        input_variables=["question"],
    )

    question_router = prompt | llm | JsonOutputParser()
    question = "llm agent memory"
    docs = retriever.invoke(question)
    doc_txt = docs[1].page_content
    question_router.invoke({"question": question})

    llm = ChatOllama(model=local_llm, format="json", temperature=0)
    
    st.write("对数据集进行聊天机器人评分.....")
    prompt = PromptTemplate(
        template="""You are a grader assessing relevance of a retrieved document to a user question. \n 
        Here is the retrieved document: \n\n {document} \n\n
        Here is the user question: {question} \n
        If the document contains keywords related to the user question, grade it as relevant. \n
        It does not need to be a stringent test. The goal is to filter out erroneous retrievals. \n
        Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question. \n
        Provide the binary score as a JSON with a single key 'score' and no premable or explaination.""",
        input_variables=["question", "document"],
    )

    retrieval_grader = prompt | llm | JsonOutputParser()
    question = "agent memory"
    docs = retriever.invoke(question)
    doc_txt = docs[1].page_content
    st.write(retrieval_grader.invoke({"question": question, "document": doc_txt}))

    # 使用 LangChain hub 来获取提示.....
    prompt = hub.pull("rlm/rag-prompt")

    # LLM
    llm = ChatOllama(model=local_llm, temperature=0)

    # Post-processing
    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    # Chain
    rag_chain = prompt | llm | StrOutputParser()

    # Run
    question = "agent memory"
    generation = rag_chain.invoke({"context": docs, "question": question})
    st.write('输出结果：')
    st.write(generation)

    llm = ChatOllama(model=local_llm, format="json", temperature=0)

    # 对提问和答案匹配度进行评分
    # Prompt
    prompt = PromptTemplate(
        template="""You are a grader assessing whether an answer is grounded in / supported by a set of facts. \n 
        Here are the facts:
        \n ------- \n
        {documents} 
        \n ------- \n
        Here is the answer: {generation}
        Give a binary score 'yes' or 'no' score to indicate whether the answer is grounded in / supported by a set of facts. \n
        Provide the binary score as a JSON with a single key 'score' and no preamble or explanation.""",
        input_variables=["generation", "documents"],
    )

    hallucination_grader = prompt | llm | JsonOutputParser()
    hallucination_grader.invoke({"documents": docs, "generation": generation})

    llm = ChatOllama(model=local_llm, format="json", temperature=0)

    # 评估给定答案在解决特定问题方面的实用性
    # Prompt
    prompt = PromptTemplate(
        template="""You are a grader assessing whether an answer is useful to resolve a question. \n 
        Here is the answer:
        \n ------- \n
        {generation} 
        \n ------- \n
        Here is the question: {question}
        Give a binary score 'yes' or 'no' to indicate whether the answer is useful to resolve a question. \n
        Provide the binary score as a JSON with a single key 'score' and no preamble or explanation.""",
        input_variables=["generation", "question"],
    )

    answer_grader = prompt | llm | JsonOutputParser()
    answer_grader.invoke({"question": question,"generation": generation})

    llm = ChatOllama(model=local_llm, temperature=0)

    # 重写问题以提高其在向量存储中的检索适用性
    # Prompt 
    re_write_prompt = PromptTemplate(
        template="""You a question re-writer that converts an input question to a better version that is optimized \n 
        for vectorstore retrieval. Look at the initial and formulate an improved question. \n
        Here is the initial question: \n\n {question}. Improved question with no preamble: \n """,
        input_variables=["generation", "question"],
    )

    question_rewriter = re_write_prompt | llm | StrOutputParser()
    question_rewriter.invoke({"question": question})

    # 网络搜索工具 tavily 来帮助提取相关主题内容
    web_search_tool = TavilySearchResults(k=3,tavily_api_key=tavily_api_key)
        

    # 状态结构  包括用户的问题、问题的生成和一个文档
    class GraphState(TypedDict):
        """
        Represents the state of our graph.

        Attributes:
            question: question
            generation: LLM generation
            documents: list of documents 
        """
        question : str
        generation : str
        documents : List[str]

    # 基于提供的问题获取相关文档
    def retrieve(state):
        """
        Retrieve documents

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): New key added to state, documents, that contains retrieved documents
        """
        st.write("---RETRIEVE---")
        question = state["question"]

        # Retrieval
        documents = retriever.invoke(question)
        return {"documents": documents, "question": question}

    # 生成答案
    def generate(state):
        """
        Generate answer

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): New key added to state, generation, that contains LLM generation
        """
        st.write("---GENERATE---")
        question = state["question"]
        documents = state["documents"]
        
        # RAG generation
        generation = rag_chain.invoke({"context": documents, "question": question})
        return {"documents": documents, "question": question, "generation": generation}

    # 检查文档的相关性
    def grade_documents(state):
        """
        Determines whether the retrieved documents are relevant to the question.

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): Updates documents key with only filtered relevant documents
        """

        st.write("---CHECK DOCUMENT RELEVANCE TO QUESTION---")
        question = state["question"]
        documents = state["documents"]
        
        # Score each doc
        filtered_docs = []
        for d in documents:
            score = retrieval_grader.invoke({"question": question, "document": d.page_content})
            grade = score['score']
            if grade == "yes":
                st.write("---GRADE: DOCUMENT RELEVANT---")
                filtered_docs.append(d)
            else:
                st.write("---GRADE: DOCUMENT NOT RELEVANT---")
                continue
        return {"documents": filtered_docs, "question": question}

    # 改进原始问题以便更好地检索
    def transform_query(state):
        """
        Transform the query to produce a better question.

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): Updates question key with a re-phrased question
        """

        st.write("---TRANSFORM QUERY---")
        question = state["question"]
        documents = state["documents"]

        # Re-write question
        better_question = question_rewriter.invoke({"question": question})
        return {"documents": documents, "question": better_question}

    # 基于重述问题的网络搜索函数。它使用网络搜索工具检索网络结果，并将它们格式化为单个文档
    def web_search(state):
        """
        Web search based on the re-phrased question.

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): Updates documents key with appended web results
        """

        st.write("---WEB SEARCH---")
        question = state["question"]

        # Web search
        docs = web_search_tool.invoke({"query": question})
        web_results = "\n".join([d["content"] for d in docs])
        web_results = Document(page_content=web_results)

        return {"documents": web_results, "question": question}

    ### Edges ###

    # 根据问题的来源决定是将问题引导到网络搜索还是 RAG
    def route_question(state):
        """
        Route question to web search or RAG.

        Args:
            state (dict): The current graph state

        Returns:
            str: Next node to call
        """

        st.write("---ROUTE QUESTION---")
        question = state["question"]
        st.write(question)
        source = question_router.invoke({"question": question})  
        st.write(source)
        st.write(source['datasource'])
        if source['datasource'] == 'web_search':
            st.write("---ROUTE QUESTION TO WEB SEARCH---")
            return "web_search"
        elif source['datasource'] == 'vectorstore':
            st.write("---ROUTE QUESTION TO RAG---")
            return "vectorstore"

    # 基于过滤文档的相关性决定是生成答案还是重新生成问题
    def decide_to_generate(state):
        """
        Determines whether to generate an answer, or re-generate a question.

        Args:
            state (dict): The current graph state

        Returns:
            str: Binary decision for next node to call
        """

        st.write("---ASSESS GRADED DOCUMENTS---")
        question = state["question"]
        filtered_documents = state["documents"]

        if not filtered_documents:
            # All documents have been filtered check_relevance
            # We will re-generate a new query
            st.write("---DECISION: ALL DOCUMENTS ARE NOT RELEVANT TO QUESTION, TRANSFORM QUERY---")
            return "transform_query"
        else:
            # We have relevant documents, so generate answer
            st.write("---DECISION: GENERATE---")
            return "generate"

    # 这个函数通过检查生成是否基于提供的文档并回答了原始问题来评估生成答案的质量
    def grade_generation_v_documents_and_question(state):
        """
        Determines whether the generation is grounded in the document and answers question.

        Args:
            state (dict): The current graph state

        Returns:
            str: Decision for next node to call
        """

        st.write("---CHECK HALLUCINATIONS---")
        question = state["question"]
        documents = state["documents"]
        generation = state["generation"]

        score = hallucination_grader.invoke({"documents": documents, "generation": generation})
        grade = score['score']

        # Check hallucination
        if grade == "yes":
            st.write("---DECISION: GENERATION IS GROUNDED IN DOCUMENTS---")
            # Check question-answering
            st.write("---GRADE GENERATION vs QUESTION---")
            score = answer_grader.invoke({"question": question,"generation": generation})
            grade = score['score']
            if grade == "yes":
                st.write("---DECISION: GENERATION ADDRESSES QUESTION---")
                return "useful"
            else:
                st.write("---DECISION: GENERATION DOES NOT ADDRESS QUESTION---")
                return "not useful"
        else:
            st.write("---DECISION: GENERATION IS NOT GROUNDED IN DOCUMENTS, RE-TRY---")
            return "not supported"

    workflow = StateGraph(GraphState)

    # Define the nodes
    workflow.add_node("web_search", web_search) # web search
    workflow.add_node("retrieve", retrieve) # retrieve
    workflow.add_node("grade_documents", grade_documents) # grade documents
    workflow.add_node("generate", generate) # generatae
    workflow.add_node("transform_query", transform_query) # transform_query

    # Build graph
    workflow.set_conditional_entry_point(
        route_question,
        {
            "web_search": "web_search",
            "vectorstore": "retrieve",
        },
    )
    workflow.add_edge("web_search", "generate")
    workflow.add_edge("retrieve", "grade_documents")
    workflow.add_conditional_edges(
        "grade_documents",
        decide_to_generate,
        {
            "transform_query": "transform_query",
            "generate": "generate",
        },
    )
    workflow.add_edge("transform_query", "retrieve")
    workflow.add_conditional_edges(
        "generate",
        grade_generation_v_documents_and_question,
        {
            "not supported": "generate",
            "useful": END,
            "not useful": "transform_query",
        },
    )

    # Compile workflow
    app = workflow.compile()

    inputs = {"question": user_input}
    for output in app.stream(inputs):
        for key, value in output.items():
            # Node
            st.write(f"Node '{key}':")
            # Optional: print full state at each node
            st.write(value)
            # pprint.pprint(value["state"], indent=2, width=80, depth=None)
        print("\n---\n")

    # Final generation
    st.write("---FINAL ANSWER---")
    st.write(value["generation"])