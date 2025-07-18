###############################################################################
#
#  Welcome to Baml! To use this generated code, please run the following:
#
#  $ pip install baml-py
#
###############################################################################

# This file was generated by BAML: please do not edit it. Instead, edit the
# BAML files and re-generate this code.
#
# ruff: noqa: E501,F401
# flake8: noqa: E501,F401
# pylint: disable=unused-import,line-too-long
# fmt: off
from typing import Any, Dict, List, Optional, Union, TypedDict, Type
from typing_extensions import NotRequired, Literal

import baml_py

from . import types
from .types import Checked, Check
from .type_builder import TypeBuilder


class BamlCallOptions(TypedDict, total=False):
    tb: NotRequired[TypeBuilder]
    client_registry: NotRequired[baml_py.baml_py.ClientRegistry]


class AsyncHttpRequest:
    __runtime: baml_py.BamlRuntime
    __ctx_manager: baml_py.BamlCtxManager

    def __init__(self, runtime: baml_py.BamlRuntime, ctx_manager: baml_py.BamlCtxManager):
      self.__runtime = runtime
      self.__ctx_manager = ctx_manager

    
    async def DirectRetrieval(
        self,
        ai_prompt: str,drhp_content: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "DirectRetrieval",
        {
          "ai_prompt": ai_prompt,
          "drhp_content": drhp_content,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractCompanyDetails(
        self,
        text: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractCompanyDetails",
        {
          "text": text,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractFinalVerdict(
        self,
        insights: str,user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractFinalVerdict",
        {
          "insights": insights,
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractPageNumber(
        self,
        image: baml_py.Image,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractPageNumber",
        {
          "image": image,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractPeopleInfo(
        self,
        text: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractPeopleInfo",
        {
          "text": text,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractResume(
        self,
        resume: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractResume",
        {
          "resume": resume,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractRetrievalAndVerdictQueries(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractRetrievalAndVerdictQueries",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractRetrievalResponses(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractRetrievalResponses",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractTableOfContents(
        self,
        page_image: baml_py.Image,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractTableOfContents",
        {
          "page_image": page_image,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def ExtractTocContent(
        self,
        page_image: baml_py.Image,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractTocContent",
        {
          "page_image": page_image,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def GetFactsFromPages(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "GetFactsFromPages",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def GetQueriesFromPages(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "GetQueriesFromPages",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    
    async def SimpleRetrieval(
        self,
        drhp_content: str,ai_prompt: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "SimpleRetrieval",
        {
          "drhp_content": drhp_content,
          "ai_prompt": ai_prompt,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        False,
      )
    


class AsyncHttpStreamRequest:
    __runtime: baml_py.BamlRuntime
    __ctx_manager: baml_py.BamlCtxManager

    def __init__(self, runtime: baml_py.BamlRuntime, ctx_manager: baml_py.BamlCtxManager):
      self.__runtime = runtime
      self.__ctx_manager = ctx_manager

    
    async def DirectRetrieval(
        self,
        ai_prompt: str,drhp_content: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "DirectRetrieval",
        {
          "ai_prompt": ai_prompt,
          "drhp_content": drhp_content,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractCompanyDetails(
        self,
        text: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractCompanyDetails",
        {
          "text": text,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractFinalVerdict(
        self,
        insights: str,user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractFinalVerdict",
        {
          "insights": insights,
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractPageNumber(
        self,
        image: baml_py.Image,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractPageNumber",
        {
          "image": image,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractPeopleInfo(
        self,
        text: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractPeopleInfo",
        {
          "text": text,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractResume(
        self,
        resume: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractResume",
        {
          "resume": resume,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractRetrievalAndVerdictQueries(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractRetrievalAndVerdictQueries",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractRetrievalResponses(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractRetrievalResponses",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractTableOfContents(
        self,
        page_image: baml_py.Image,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractTableOfContents",
        {
          "page_image": page_image,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def ExtractTocContent(
        self,
        page_image: baml_py.Image,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "ExtractTocContent",
        {
          "page_image": page_image,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def GetFactsFromPages(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "GetFactsFromPages",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def GetQueriesFromPages(
        self,
        user_query: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "GetQueriesFromPages",
        {
          "user_query": user_query,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    
    async def SimpleRetrieval(
        self,
        drhp_content: str,ai_prompt: str,
        baml_options: BamlCallOptions = {},
    ) -> baml_py.HTTPRequest:
      __tb__ = baml_options.get("tb", None)
      if __tb__ is not None:
        tb = __tb__._tb # type: ignore (we know how to use this private attribute)
      else:
        tb = None
      __cr__ = baml_options.get("client_registry", None)

      return await self.__runtime.build_request(
        "SimpleRetrieval",
        {
          "drhp_content": drhp_content,
          "ai_prompt": ai_prompt,
        },
        self.__ctx_manager.get(),
        tb,
        __cr__,
        True,
      )
    


__all__ = ["AsyncHttpRequest", "AsyncHttpStreamRequest"]